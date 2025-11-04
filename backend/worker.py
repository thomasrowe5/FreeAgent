import asyncio
import os

from celery import Celery

from backend.jobs import poll_gmail_for_leads
from backend.orchestrator import Workflow
from backend.integrations.gmail import send_email as gmail_send_email


def _broker_url() -> str:
    return os.getenv("CELERY_BROKER_URL") or os.getenv("REDIS_URL", "redis://localhost:6379/0")


celery_app = Celery(
    "freeagent",
    broker=_broker_url(),
    backend=os.getenv("CELERY_RESULT_BACKEND", _broker_url()),
)


@celery_app.task
def send_email_task(user_id: str, recipient: str, subject: str, body: str) -> None:
    asyncio.run(gmail_send_email(user_id, recipient, subject, body))


@celery_app.task
def poll_gmail_task() -> None:
    asyncio.run(poll_gmail_for_leads())


@celery_app.task
def run_workflow_task(lead_id: int, user_id: str, start_from: str = "score") -> None:
    asyncio.run(Workflow(lead_id, user_id).run(start_from=start_from))
