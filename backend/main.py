import asyncio
import os
from typing import Any, Optional
from uuid import uuid4

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import select

from backend import billing, feedback, monitoring
from backend.analytics import get_user_summary, recompute_all_snapshots, recompute_snapshot_for_user
from backend.auth import SupabaseAuthMiddleware
from backend.db import GmailToken, InviteToken, Lead, Proposal, RunHistory, get_session, init_db
from backend.integrations.gmail import (
    exchange_code_for_token,
    get_authorize_url,
    send_email as gmail_send_email,
)
from backend.jobs import poll_gmail_for_leads
from backend.orchestrator import Workflow
from backend.schemas import (
    FollowupIn,
    FeedbackIn,
    InviteIn,
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


@app.on_event("startup")
async def on_startup():
    await init_db()
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
    async with get_session() as session:
        lead = Lead(
            user_id=request.state.user_id,
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
        )
    workflow = Workflow(lead.id, request.state.user_id)
    workflow.enqueue()
    return response


@app.get("/leads", response_model=list[LeadOut])
async def list_leads(request: Request):
    async with get_session() as session:
        statement = (
            select(Lead).where(Lead.user_id == request.state.user_id).order_by(Lead.id.desc())
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
            )
            for lead in leads
        ]


@app.post("/proposals", response_model=ProposalOut)
async def generate_proposal(payload: ProposalIn, request: Request):
    async with get_session() as session:
        lead = await session.get(Lead, payload.lead_id)
        if not lead or lead.user_id != request.state.user_id:
            raise HTTPException(status_code=404, detail="Lead not found")

    workflow = Workflow(payload.lead_id, request.state.user_id)
    try:
        await workflow.run(start_from="proposal")
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
        )


@app.post("/followups")
async def schedule_followup(payload: FollowupIn, request: Request):
    async with get_session() as session:
        lead = await session.get(Lead, payload.lead_id)
        if not lead or lead.user_id != request.state.user_id:
            raise HTTPException(status_code=404, detail="Lead not found")

    workflow = Workflow(payload.lead_id, request.state.user_id)
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
    _ = request.state.user_id  # ensure middleware runs
    try:
        url = get_authorize_url()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"authorize_url": url}


@app.post("/gmail/callback")
async def gmail_callback(payload: GmailCallbackIn, request: Request):
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
            session.add(record)
        else:
            session.add(
                GmailToken(
                    user_id=request.state.user_id,
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
    try:
        result: Any = await gmail_send_email(
            request.state.user_id, payload.to, payload.subject, payload.body
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, "message_id": result.get("id")}


@app.get("/analytics/summary")
async def analytics_summary(request: Request, start: Optional[str] = None, end: Optional[str] = None, client_type: Optional[str] = None):
    summary = await get_user_summary(
        request.state.user_id,
        start=start,
        end=end,
        client_type=client_type,
    )
    return summary


@app.post("/analytics/recompute")
async def analytics_recompute(request: Request):
    await recompute_snapshot_for_user(request.state.user_id)
    summary = await get_user_summary(request.state.user_id)
    return summary


@app.get("/billing/status")
async def billing_status(request: Request):
    status = await billing.get_status(request.state.user_id)
    return status


@app.post("/billing/upgrade")
async def billing_upgrade(request: Request):
    url = await billing.create_checkout_session(request.state.user_id)
    return {"checkout_url": url}


@app.post("/invite")
async def generate_invite(payload: InviteIn, request: Request):
    token = uuid4().hex
    async with get_session() as session:
        invite = InviteToken(token=token, email=payload.email, redeemed=False)
        session.add(invite)
        await session.commit()
    return {"token": token}


@app.post("/feedback")
async def submit_feedback(payload: FeedbackIn, request: Request):
    entry = await feedback.save_feedback(
        user_id=request.state.user_id,
        lead_id=payload.lead_id,
        feedback_type=payload.type,
        comment=payload.comment,
        edited_text=payload.edited_text,
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
    data = await feedback.aggregate_feedback(request.state.user_id)
    return data


@app.get("/runs")
async def recent_runs(request: Request, limit: int = 50):
    async with get_session() as session:
        entries = (
            await session.exec(
                select(RunHistory)
                .where(RunHistory.user_id == request.state.user_id)
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
    return {"user_id": request.state.user_id, "email": request.state.email}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=API_PORT)
