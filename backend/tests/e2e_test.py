import os
from importlib import reload
from pathlib import Path

import jwt
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlmodel import select

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def app_context(monkeypatch, tmp_path):
    db_path = tmp_path / "test_e2e.db"
    secret = "test-secret"

    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", secret)
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "fake-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "fake-client-secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost/callback")
    monkeypatch.setenv("SENTRY_DSN", "")
    monkeypatch.setenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("API_PORT", "8000")

    import backend.monitoring as monitoring_module
    import backend.billing as billing_module
    import backend.db as db
    import backend.analytics as analytics
    import backend.integrations.gmail as gmail
    import backend.jobs as jobs
    import backend.main as main
    import backend.feedback as feedback_module
    import backend.orchestrator as orchestrator

    for module in (monitoring_module, billing_module, feedback_module, db, analytics, gmail, jobs, main):
        reload(module)

    await db.init_db()

    # Ensure LLM agents fall back to deterministic responses
    monkeypatch.setattr("backend.agents.lead_scoring._get_client", lambda: None)
    monkeypatch.setattr("backend.agents.proposal_gen._get_client", lambda: None)
    monkeypatch.setattr("backend.agents.followups._get_client", lambda: None)

    # Stub scheduler to avoid background threads during tests
    class DummyScheduler:
        def __init__(self):
            self.running = False

        def start(self):
            self.running = True

        def add_job(self, *args, **kwargs):
            return None

        def get_job(self, job_id):
            return None

        def shutdown(self, wait=False):
            self.running = False

    monkeypatch.setattr(main, "scheduler", DummyScheduler())

    # Stub Google OAuth helpers
    fake_tokens = {
        "access_token": "test-access-token",
        "refresh_token": "test-refresh-token",
        "expiry": None,
    }

    monkeypatch.setattr(main, "exchange_code_for_token", lambda code: fake_tokens)
    monkeypatch.setattr(gmail, "exchange_code_for_token", lambda code: fake_tokens)
    monkeypatch.setattr(main, "get_authorize_url", lambda: "https://example.com/consent")
    monkeypatch.setattr(gmail, "get_authorize_url", lambda state=None: "https://example.com/consent")

    # Capture follow-up text to verify generation
    captured_followups = {}

    def compose_stub(name, days_after, last_message=""):
        message = f"Follow-up to {name} after {days_after} days"
        captured_followups["message"] = message
        return message

    monkeypatch.setattr("backend.agents.followups.compose", compose_stub)
    monkeypatch.setattr(main, "compose_followup", compose_stub)

    # Prevent startup hooks from invoking real side effects
    async def noop():
        return None

    monkeypatch.setattr(main, "poll_gmail_for_leads", noop)
    monkeypatch.setattr(main, "recompute_all_snapshots", noop)

    threads_holder = {"threads": []}

    async def list_threads_stub(user_id, label="INBOX", max=10):
        return threads_holder["threads"]

    monkeypatch.setattr("backend.integrations.gmail.list_inbox_threads", list_threads_stub)
    monkeypatch.setattr("backend.jobs.list_inbox_threads", list_threads_stub)

    sent_emails = []

    async def fake_send_email(user_id, to, subject, body):
        sent_emails.append({"to": to, "subject": subject, "body": body})
        return {"id": "message-id"}

    monkeypatch.setattr(gmail, "send_email", fake_send_email)
    monkeypatch.setattr(orchestrator, "gmail_send_email", fake_send_email)
    monkeypatch.setattr(orchestrator, "compose_followup", compose_stub)

    # Reload jobs and main so patched dependencies are consistent
    reload(jobs)
    reload(main)
    reload(orchestrator)

    # Apply stubs again after reload
    monkeypatch.setattr(main, "scheduler", DummyScheduler())
    monkeypatch.setattr(main, "exchange_code_for_token", lambda code: fake_tokens)
    monkeypatch.setattr(gmail, "exchange_code_for_token", lambda code: fake_tokens)
    monkeypatch.setattr(main, "get_authorize_url", lambda: "https://example.com/consent")
    monkeypatch.setattr(gmail, "get_authorize_url", lambda state=None: "https://example.com/consent")
    monkeypatch.setattr(main, "compose_followup", compose_stub)
    monkeypatch.setattr(main, "poll_gmail_for_leads", noop)
    monkeypatch.setattr(main, "recompute_all_snapshots", noop)
    monkeypatch.setattr("backend.jobs.list_inbox_threads", list_threads_stub)
    monkeypatch.setattr(orchestrator, "gmail_send_email", fake_send_email)
    monkeypatch.setattr(orchestrator, "compose_followup", compose_stub)

    await db.init_db()

    try:
        yield {
            "app": main.app,
            "jobs": jobs,
            "db": db,
            "secret": secret,
            "threads": threads_holder,
            "captured_followups": captured_followups,
            "sent_emails": sent_emails,
            "db_path": db_path,
        }
    finally:
        await db.engine.dispose()
        if Path(db_path).exists():
            os.remove(db_path)


async def test_full_pipeline(app_context):
    app = app_context["app"]
    jobs = app_context["jobs"]
    db = app_context["db"]
    secret = app_context["secret"]
    threads_holder = app_context["threads"]
    captured_followups = app_context["captured_followups"]

    user_id = "user-e2e"
    user_email = "user@example.com"
    token = jwt.encode({"sub": user_id, "email": user_email}, secret, algorithm="HS256")
    headers = {"Authorization": f"Bearer {token}"}

    transport = ASGITransport(app=app, lifespan="on")
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Health check
        health = await client.get("/healthz")
        assert health.status_code == 200

        # Gmail OAuth flow (stubbed)
        connect = await client.get("/gmail/connect", headers=headers)
        assert connect.status_code == 200
        assert "authorize_url" in connect.json()

        callback = await client.post("/gmail/callback", json={"code": "fake-code"}, headers=headers)
        assert callback.status_code == 200

        # Simulate inbox polling to create a lead and run workflow
        threads_holder["threads"] = [
            {
                "id": "thread-123",
                "snippet": "Interested in MVP build",
                "subject": "Project inquiry",
                "from_name": "Prospect Test",
                "from_email": "prospect@example.com",
                "message": "We have a budget of $5000 and need an MVP in 3 weeks.",
            }
        ]
        await jobs.poll_gmail_for_leads()

        leads_resp = await client.get("/leads", headers=headers)
        assert leads_resp.status_code == 200
        leads = leads_resp.json()
        assert len(leads) == 1
        lead = leads[0]
        assert lead["email"] == "prospect@example.com"
        lead_id = lead["id"]
        assert lead["status"] == "followup_pending"
        assert lead["client_type"] == "general"
        assert lead["org_id"]

        # Verify proposal persisted
        async with db.get_session() as session:
            proposal = (
                await session.exec(
                    select(db.Proposal)
                    .where(db.Proposal.lead_id == lead_id)
                    .order_by(db.Proposal.created_at.desc())
                    .limit(1)
                )
            ).first()
            assert proposal is not None
            assert "FreeAgent" in proposal.content

        assert captured_followups["message"].startswith("Follow-up to Prospect Test")
        assert app_context["sent_emails"]

        # Analytics summary
        analytics_resp = await client.get("/analytics/summary", headers=headers)
        assert analytics_resp.status_code == 200
        summary = analytics_resp.json()

        assert summary["leads"] == 1
        assert summary["proposals"] == 1
        assert summary["followups"] == 1
        assert summary["status_breakdown"]["followup_pending"] == 1
        assert summary["wins"] == 0
        assert isinstance(summary.get("revenue_by_month"), list)

        runs_resp = await client.get("/runs", headers=headers)
        assert runs_resp.status_code == 200
        runs = runs_resp.json()
        stages = {entry["stage"] for entry in runs}
        assert {"lead_scoring", "proposal_generation", "followup"}.issubset(stages)

        billing_resp = await client.get("/billing/status", headers=headers)
        assert billing_resp.status_code == 200
        billing_status = billing_resp.json()
        assert billing_status["usage"] >= 2
        assert billing_status["plan"]
