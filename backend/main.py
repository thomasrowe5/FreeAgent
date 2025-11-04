import asyncio
import json
import os
from typing import Any, Dict, List, Optional
from uuid import uuid4

"""Main FastAPI application and orchestration endpoints for FreeAgent."""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import select

from backend import billing, feedback, monitoring
from backend.analytics import (
    get_user_summary,
    recompute_all_snapshots,
    recompute_snapshot_for_user,
    revenue_overview,
)
from backend.analytics import realtime
from backend.auth import SupabaseAuthMiddleware
from backend.db import GmailToken, InviteToken, Lead, Proposal, RunHistory, User, get_session, init_db
from backend.integrations.gmail import (
    exchange_code_for_token,
    get_authorize_url,
    send_email as gmail_send_email,
)
from backend.integrations import slack, notion, hubspot
from backend.jobs import poll_gmail_for_leads
from backend.orchestrator import Workflow
from backend.orchestrator.graph import DAGRuntime, DAG_RUN_HISTORY, default_spec
from backend.memory.context import add_memory, get_memory, search_memory
from backend.memory import vector_memory
from backend.feedback.loop import feedback_loop
from backend.agents.registry import registry as agent_registry
from backend.reward.optimizer import optimizer
from backend.self_optimize import optimizer as self_optimizer
from backend.branding.routes import router as branding_router
from backend.schemas import (
    FollowupIn,
    FeedbackIn,
    InviteIn,
    MemoryAddIn,
    MemorySearchIn,
    AgentConfigUpdateIn,
    GmailCallbackIn,
    GmailSendIn,
    LeadIn,
    LeadOut,
    ProposalIn,
    ProposalOut,
)

API_PORT = int(os.getenv("API_PORT", "8000"))

monitoring.init_monitoring()

scheduler = AsyncIOScheduler()
websocket_clients: List[WebSocket] = []


async def broadcast_dag_run(run: Dict[str, Any]) -> None:
    """Send DAG run updates to connected websocket clients."""
    stale: List[WebSocket] = []
    for ws in websocket_clients:
        try:
            await ws.send_json(run)
        except Exception:
            stale.append(ws)
    for ws in stale:
        websocket_clients.remove(ws)


def _integration_status() -> List[Dict[str, Any]]:
    return [
        {
            "key": "slack",
            "name": "Slack",
            "configured": slack.is_configured(),
            "details": {"requires_oauth": True},
        },
        {
            "key": "notion",
            "name": "Notion",
            "configured": notion.is_configured(),
            "details": {"requires_oauth": True},
        },
        {
            "key": "hubspot",
            "name": "HubSpot",
            "configured": hubspot.is_configured(),
            "details": {"requires_oauth": True},
        },
    ]

app = FastAPI(title="FreeAgent API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(
    SupabaseAuthMiddleware,
    exempt_paths={"/healthz"},
    exempt_prefixes={"/docs", "/openapi", "/redoc"},
)

app.include_router(branding_router)


@app.on_event("startup")
async def on_startup():
    await init_db()
    agent_registry.load()
    if not scheduler.running:
        scheduler.start()
    if not scheduler.get_job("gmail-poller"):
        scheduler.add_job(
            lambda: asyncio.create_task(poll_gmail_for_leads()),
            "interval",
            minutes=15,
            id="gmail-poller",
        )
    if not scheduler.get_job("analytics-snapshots"):
        scheduler.add_job(
            lambda: asyncio.create_task(recompute_all_snapshots()),
            "cron",
            hour=3,
            minute=0,
            id="analytics-snapshots",
        )
    if not scheduler.get_job("feedback-analysis"):
        scheduler.add_job(
            lambda: asyncio.create_task(feedback.analyze_feedback()),
            "cron",
            hour=2,
            minute=0,
            id="feedback-analysis",
        )
    if not scheduler.get_job("self-optimize-weekly"):
        scheduler.add_job(
            lambda: asyncio.create_task(self_optimizer.run()),
            "cron",
            day_of_week="mon",
            hour=4,
            minute=0,
            id="self-optimize-weekly",
        )
    await poll_gmail_for_leads()
    await recompute_all_snapshots()


@app.on_event("shutdown")
async def on_shutdown():
    if scheduler.running:
        scheduler.shutdown(wait=False)


@app.get("/healthz")
async def health_check():
    return {"status": "ok"}


@app.post("/leads", response_model=LeadOut)
async def create_lead(payload: LeadIn, request: Request):
    """Create a new lead, enqueue the workflow, and return the persisted record.

    Args:
        payload: Lead details submitted by the client.
        request: FastAPI request providing authenticated user context.

    Returns:
        LeadOut: The created lead with scoring and status metadata.
    """
    async with get_session() as session:
        lead = Lead(
            user_id=request.state.user_id,
            org_id=request.state.org_id,
            name=payload.name,
            email=payload.email,
            message=payload.message,
            score=0.0,
            value=payload.value or 0.0,
            client_type=payload.client_type or "general",
        )
        session.add(lead)
        await session.commit()
        await session.refresh(lead)
        response = LeadOut(
            id=lead.id,
            name=lead.name,
            email=lead.email,
            message=lead.message,
            score=lead.score,
            status=lead.status,
            value=lead.value,
            client_type=lead.client_type,
            created_at=lead.created_at,
            org_id=lead.org_id,
        )
    workflow = Workflow(lead.id, request.state.user_id, request.state.org_id)
    workflow.enqueue()
    return response


@app.get("/leads", response_model=list[LeadOut])
async def list_leads(request: Request):
    """List recent leads scoped to the authenticated organization.

    Args:
        request: FastAPI request providing auth context.

    Returns:
        list[LeadOut]: Ordered list of leads.
    """
    async with get_session() as session:
        statement = (
            select(Lead)
            .where(Lead.org_id == request.state.org_id)
            .order_by(Lead.id.desc())
        )
        leads = (await session.exec(statement)).all()
        return [
            LeadOut(
                id=lead.id,
                name=lead.name,
                email=lead.email,
                message=lead.message,
                score=lead.score,
                status=lead.status,
                value=lead.value,
                client_type=lead.client_type,
                created_at=lead.created_at,
                org_id=lead.org_id,
            )
            for lead in leads
        ]


@app.post("/proposals", response_model=ProposalOut)
async def generate_proposal(payload: ProposalIn, request: Request):
    """Generate a proposal for a lead and return the most recent document.

    Args:
        payload: Identifies the lead that requires a proposal.
        request: FastAPI request carrying user and org identifiers.

    Returns:
        ProposalOut: The persisted proposal content.
    """
    async with get_session() as session:
        lead = await session.get(Lead, payload.lead_id)
        if not lead or lead.org_id != request.state.org_id:
            raise HTTPException(status_code=404, detail="Lead not found")

    workflow = Workflow(payload.lead_id, request.state.user_id, request.state.org_id)
    try:
        workflow_result = await workflow.run(start_from="proposal")
    except billing.UsageLimitExceeded as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc

    async with get_session() as session:
        proposal = (
            await session.exec(
                select(Proposal)
                .where(Proposal.lead_id == payload.lead_id)
                .order_by(Proposal.created_at.desc())
                .limit(1)
            )
        ).first()
        if not proposal:
            raise HTTPException(status_code=500, detail="Proposal generation failed")
        return ProposalOut(
            id=proposal.id,
            lead_id=proposal.lead_id,
            content=proposal.content,
            created_at=proposal.created_at,
            reward_score=workflow_result.reward_score or workflow.last_reward,
        )


@app.post("/followups")
async def schedule_followup(payload: FollowupIn, request: Request):
    """Schedule follow-up tasks for a lead and update status in storage.

    Args:
        payload: Follow-up scheduling parameters.
        request: FastAPI request providing auth context.

    Returns:
        dict: Confirmation payload with lead status.
    """
    async with get_session() as session:
        lead = await session.get(Lead, payload.lead_id)
        if not lead or lead.org_id != request.state.org_id:
            raise HTTPException(status_code=404, detail="Lead not found")

    workflow = Workflow(payload.lead_id, request.state.user_id, request.state.org_id)
    try:
        await workflow.run(start_from="followup")
    except billing.UsageLimitExceeded as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc

    async with get_session() as session:
        lead = await session.get(Lead, payload.lead_id)
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        return {"ok": True, "lead_id": lead.id, "status": lead.status}


@app.get("/gmail/connect")
async def gmail_connect(request: Request):
    """Return the OAuth authorize URL for attaching a Gmail account.

    Args:
        request: FastAPI request ensuring middleware execution.

    Returns:
        dict: Authorization URL payload.
    """
    _ = request.state.user_id  # ensure middleware runs
    try:
        url = get_authorize_url()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"authorize_url": url}


@app.post("/gmail/callback")
async def gmail_callback(payload: GmailCallbackIn, request: Request):
    """Persist Gmail OAuth tokens after the user completes consent.

    Args:
        payload: OAuth authorization code wrapper.
        request: FastAPI request with user/org context.

    Returns:
        dict: Simple acknowledgement response.
    """
    try:
        tokens = exchange_code_for_token(payload.code)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    async with get_session() as session:
        record = await session.get(GmailToken, request.state.user_id)
        if record:
            record.access_token = tokens["access_token"]
            record.refresh_token = tokens.get("refresh_token") or record.refresh_token
            record.expiry = tokens.get("expiry")
            record.org_id = request.state.org_id
            session.add(record)
        else:
            session.add(
                GmailToken(
                    user_id=request.state.user_id,
                    org_id=request.state.org_id,
                    access_token=tokens["access_token"],
                    refresh_token=tokens.get("refresh_token"),
                    expiry=tokens.get("expiry"),
                )
            )
        await session.commit()
    await poll_gmail_for_leads()
    return {"ok": True}


@app.post("/gmail/send")
async def gmail_send(payload: GmailSendIn, request: Request):
    """Send an email via the user's connected Gmail account.

    Args:
        payload: Email fields (to, subject, body).
        request: FastAPI request containing auth context.

    Returns:
        dict: Gmail API response metadata.
    """
    try:
        result: Any = await gmail_send_email(
            request.state.user_id, payload.to, payload.subject, payload.body
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, "message_id": result.get("id")}


@app.get("/analytics/summary")
async def analytics_summary(request: Request, start: Optional[str] = None, end: Optional[str] = None, client_type: Optional[str] = None):
    """Return KPI summary data filtered by optional date range and client type.

    Args:
        request: FastAPI request for auth context.
        start: Optional ISO timestamp filter.
        end: Optional ISO timestamp filter.
        client_type: Optional client category filter.

    Returns:
        dict: Aggregated analytics payload.
    """
    summary = await get_user_summary(
        request.state.user_id,
        request.state.org_id,
        start=start,
        end=end,
        client_type=client_type,
    )
    return summary


@app.post("/analytics/recompute")
async def analytics_recompute(request: Request):
    """Recompute analytics snapshot for the active user and return the latest metrics.

    Args:
        request: FastAPI request for auth context.

    Returns:
        dict: Updated analytics summary.
    """
    await recompute_snapshot_for_user(request.state.user_id, request.state.org_id)
    summary = await get_user_summary(request.state.user_id, request.state.org_id)
    return summary


@app.get("/analytics/revenue")
async def analytics_revenue(request: Request):
    """Expose revenue totals and conversion rate grouped by month.

    Args:
        request: FastAPI request for auth context.

    Returns:
        dict: Revenue overview with monthly breakdown.
    """
    data = await revenue_overview(request.state.user_id, request.state.org_id)
    return data


@app.get("/optimize")
async def optimize_prompts(request: Request):
    """Execute the reward optimizer to refresh agent prompts from feedback.

    Args:
        request: FastAPI request for auth context.

    Returns:
        dict: Summary of optimization tasks performed.
    """
    _ = request.state.user_id  # ensure auth middleware runs
    result = await asyncio.to_thread(optimizer.run)
    return result


@app.post("/self_optimize")
async def trigger_self_optimize(request: Request):
    """Run the self-optimization pipeline on demand and return the latest report metadata.

    Args:
        request: FastAPI request for auth context.

    Returns:
        dict: Paths and summaries for generated reports.
    """
    _ = request.state.user_id  # ensure auth middleware runs
    result = await self_optimizer.run()
    return result


@app.get("/billing/status")
async def billing_status(request: Request):
    """Return the current usage totals and plan limits for the active organization.

    Args:
        request: FastAPI request for auth context.

    Returns:
        dict: Plan name, usage totals, and remaining quota.
    """
    status = await billing.get_status(request.state.org_id)
    return status


@app.post("/billing/upgrade")
async def billing_upgrade(request: Request):
    """Create a Stripe checkout session URL for upgrading the current plan.

    Args:
        request: FastAPI request for auth context.

    Returns:
        dict: Checkout link for upgrading billing.
    """
    url = await billing.create_checkout_session(request.state.org_id)
    return {"checkout_url": url}


async def _create_invite_token(request: Request, email: Optional[str]) -> Dict[str, Any]:
    """Create a single-use invite token scoped to the current organization.

    Args:
        request: FastAPI request containing org context.
        email: Optional email address to prefill for invitee.

    Returns:
        dict: Token payload.
    """
    token = uuid4().hex
    async with get_session() as session:
        invite = InviteToken(token=token, email=email, org_id=request.state.org_id, redeemed=False)
        session.add(invite)
        await session.commit()
    return {"token": token}


@app.post("/invite")
async def generate_invite(payload: InviteIn, request: Request):
    """Generate an invitation token for onboarding collaborators.

    Args:
        payload: Invite request containing optional email.
        request: FastAPI request with org context.

    Returns:
        dict: Invite token payload.
    """
    return await _create_invite_token(request, payload.email)


@app.post("/org/invite")
async def org_invite(payload: InviteIn, request: Request):
    """Alias for generating an organization-level invite token.

    Args:
        payload: Invite request containing optional email.
        request: FastAPI request with org context.

    Returns:
        dict: Invite token payload.
    """
    return await _create_invite_token(request, payload.email)


@app.get("/org/members")
async def org_members(request: Request):
    """List organization members along with current usage summary.

    Args:
        request: FastAPI request with org context.

    Returns:
        dict: Member roster and usage stats.
    """
    async with get_session() as session:
        members = (
            await session.exec(select(User).where(User.org_id == request.state.org_id))
        ).all()
    usage = await billing.get_usage(request.state.org_id)
    return {
        "members": [
            {
                "id": member.id,
                "email": member.email,
            }
            for member in members
        ],
        "usage": usage,
    }


@app.post("/feedback")
async def submit_feedback(payload: FeedbackIn, request: Request):
    """Persist feedback, update memory, and return the stored record.

    Args:
        payload: Feedback details and optional edited text.
        request: FastAPI request with auth context.

    Returns:
        dict: Normalized feedback resource.
    """
    entry = await feedback.save_feedback(
        user_id=request.state.user_id,
        org_id=request.state.org_id,
        lead_id=payload.lead_id,
        feedback_type=payload.type,
        comment=payload.comment,
        edited_text=payload.edited_text,
    )
    await add_memory(
        user_id=request.state.user_id,
        org_id=request.state.org_id,
        key=f"lead:{payload.lead_id}:feedback" if payload.lead_id else f"feedback:{entry.id}",
        value=(payload.edited_text or payload.comment or ""),
        payload={"lead_id": payload.lead_id, "type": payload.type},
    )
    return {
        "id": entry.id,
        "lead_id": entry.lead_id,
        "type": entry.type,
        "comment": entry.comment,
        "edited_text": entry.edited_text,
        "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
    }


@app.get("/feedback/aggregate")
async def feedback_aggregate(request: Request):
    """Aggregate feedback counts by type for the active user.

    Args:
        request: FastAPI request with auth context.

    Returns:
        list[dict]: Feedback types with occurrence counts.
    """
    data = await feedback.aggregate_feedback(request.state.user_id, request.state.org_id)
    return data


@app.get("/feedback/export_dataset")
async def feedback_export_dataset(request: Request):
    """Export feedback records into a JSONL dataset for fine-tuning workflows.

    Args:
        request: FastAPI request with auth context.

    Returns:
        dict: Export count and file path.
    """
    count, path = await feedback.export_dataset(request.state.org_id)
    return {"count": count, "path": str(path)}


@app.get("/feedback/insights")
async def feedback_insights(request: Request):
    """Return feedback insights and keyword summaries per agent.

    Args:
        request: FastAPI request with auth context.

    Returns:
        dict: Keyword-driven insights grouped by agent.
    """
    return await feedback.insights(request.state.org_id)


@app.get("/integrations/status")
async def integrations_status(request: Request):
    """Report readiness of Slack, Notion, and HubSpot integrations for the user.

    Args:
        request: FastAPI request with auth context.

    Returns:
        dict: Integration readiness details.
    """
    _ = request.state.user_id  # ensure auth middleware runs
    return {"integrations": _integration_status()}


@app.post("/memory/add")
async def memory_add(payload: MemoryAddIn, request: Request):
    """Persist a manual memory entry for the active user/org.

    Args:
        payload: Memory content and optional payload metadata.
        request: FastAPI request with auth context.

    Returns:
        dict: Newly created memory record.
    """
    entry = await add_memory(
        user_id=request.state.user_id,
        org_id=request.state.org_id,
        key=payload.key,
        value=payload.value,
        payload=payload.payload,
    )
    return entry.model_dump()


@app.get("/memory/get")
async def memory_get(request: Request, key: str):
    """Fetch stored memory entries matching the provided key.

    Args:
        request: FastAPI request with auth context.
        key: Memory namespace identifier.

    Returns:
        list[dict]: Stored memory entries.
    """
    entries = await get_memory(request.state.user_id, request.state.org_id, key)
    return [entry.model_dump() for entry in entries]


@app.post("/memory/search")
async def memory_search(payload: MemorySearchIn, request: Request):
    """Search semantic memory for relevant entries and return scored matches.

    Args:
        payload: Query text and limit configuration.
        request: FastAPI request with auth context.

    Returns:
        list[dict]: Matching memory items with scores.
    """
    results = await search_memory(
        request.state.user_id,
        request.state.org_id,
        query=payload.query,
        limit=payload.limit,
    )
    return results


@app.get("/memory/{agent}")
async def memory_agent(agent: str, request: Request, limit: int = 10):
    """Retrieve recent vector-memory context items for the specified agent.

    Args:
        agent: Agent identifier (lead_scorer, proposal_gen, followups).
        request: FastAPI request with auth context.
        limit: Maximum number of items to return.

    Returns:
        list[dict]: Recent vector memory payloads.
    """
    _ = request.state.user_id  # ensure auth middleware runs
    items = await asyncio.to_thread(vector_memory.get_recent, agent, limit)
    return items


@app.get("/agents/status")
async def agents_status(request: Request):
    """Return aggregated KPI status for all registered agents.

    Args:
        request: FastAPI request with auth context.

    Returns:
        list[dict]: Agent KPI summaries.
    """
    return await agent_registry.status(request.state.org_id)


@app.get("/agents/config/{name}")
async def agent_config_detail(name: str):
    """Fetch persisted configuration for the requested agent.

    Args:
        name: Agent identifier.

    Returns:
        dict: Agent configuration document.
    """
    config = agent_registry.get_config(name)
    if not config:
        raise HTTPException(status_code=404, detail="Agent not found")
    return config


@app.post("/agents/config/update")
async def agent_config_update(payload: AgentConfigUpdateIn):
    """Persist prompt updates for an agent.

    Args:
        payload: Agent name and updated prompt template.

    Returns:
        dict: Success indicator.
    """
    try:
        agent_registry.update_prompt(payload.name, payload.prompt_template)
    except KeyError:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"ok": True}


@app.post("/orchestrate")
async def orchestrate(request: Request):
    """Run a DAG-based orchestration spec and broadcast the execution result.

    Args:
        request: FastAPI request containing optional DAG specification.

    Returns:
        dict: Runtime execution payload.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    spec = body if isinstance(body, dict) and body.get("tasks") else default_spec()
    spec = json.loads(json.dumps(spec))
    spec_context = spec.setdefault("context", {})
    spec_context.setdefault("user_id", request.state.user_id)
    spec_context.setdefault("org_id", request.state.org_id)
    runtime = DAGRuntime(spec)
    result = await runtime.run()
    await broadcast_dag_run(result)
    return result


@app.get("/orchestrate/runs")
async def orchestrate_runs(request: Request):
    """Return orchestrator run history filtered by organization."""
    runs = [
        run
        for run in DAG_RUN_HISTORY
        if run.get("context", {}).get("org_id") == request.state.org_id
    ]
    return {"runs": runs}


@app.websocket("/orchestrate/ws")
async def orchestrate_ws(websocket: WebSocket):
    """Stream orchestrator updates to connected dashboard clients."""
    await websocket.accept()
    websocket_clients.append(websocket)
    try:
        await websocket.send_json({"runs": list(DAG_RUN_HISTORY)})
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in websocket_clients:
            websocket_clients.remove(websocket)


@app.websocket("/ws/metrics")
async def metrics_ws(websocket: WebSocket):
    """Stream realtime agent run metrics to the dashboard."""
    await websocket.accept()
    org_filter = websocket.query_params.get("org") if websocket.query_params else None
    queue = await realtime.subscribe(org_filter)
    try:
        while True:
            event = await queue.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        await realtime.unsubscribe(queue)


@app.get("/logs/recent")
async def logs_recent(request: Request, limit: int = 50):
    """Return recent RunHistory records for quick diagnostics."""
    async with get_session() as session:
        rows = (
            await session.exec(
                select(RunHistory)
                .where(RunHistory.org_id == request.state.org_id)
                .order_by(RunHistory.timestamp.desc())
                .limit(limit)
            )
        ).all()
    return [
        {
            "stage": row.stage,
            "status": row.success,
            "duration_ms": row.duration_ms,
            "error": row.error_text,
            "timestamp": row.timestamp.isoformat() if row.timestamp else None,
        }
        for row in rows
    ]


@app.get("/runs")
async def recent_runs(request: Request, limit: int = 50):
    """Return structured run history entries for analytics tabs."""
    async with get_session() as session:
        entries = (
            await session.exec(
                select(RunHistory)
                .where(RunHistory.org_id == request.state.org_id)
                .order_by(RunHistory.timestamp.desc())
                .limit(limit)
            )
        ).all()
    return [
        {
            "id": entry.id,
            "lead_id": entry.lead_id,
            "stage": entry.stage,
            "success": entry.success,
            "error_text": entry.error_text,
            "duration_ms": entry.duration_ms,
            "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
        }
        for entry in entries
    ]


@app.get("/auth/verify")
async def verify_auth(request: Request):
    """Verify Supabase authentication and echo user metadata."""
    return {"user_id": request.state.user_id, "email": request.state.email}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=API_PORT)
