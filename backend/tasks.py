import asyncio
import os
from typing import Optional

from celery import Celery

from backend.analytics import recompute_all_snapshots
from backend.jobs import poll_gmail_for_leads
from backend.orchestrator import Workflow


def _get_broker_url() -> str:
    return os.getenv("CELERY_BROKER_URL") or os.getenv("REDIS_URL", "redis://localhost:6379/0")


celery_app = Celery(
    "freeagent",
    broker=_get_broker_url(),
    backend=os.getenv("CELERY_RESULT_BACKEND", _get_broker_url()),
)


@celery_app.task
def poll_gmail_task() -> None:
    asyncio.run(poll_gmail_for_leads())


@celery_app.task
def recompute_analytics_task() -> None:
    asyncio.run(recompute_all_snapshots())


@celery_app.task
def run_workflow_task(lead_id: int, user_id: str, org_id: Optional[str] = None, start_from: str = "score") -> None:
    asyncio.run(Workflow(lead_id, user_id, org_id).run(start_from=start_from))
