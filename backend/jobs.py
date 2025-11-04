import logging
from typing import Sequence

from sqlmodel import select

from backend import monitoring
from backend.db import GmailThread, GmailToken, Lead, User, get_session
from backend.integrations.gmail import list_inbox_threads
from backend.orchestrator import Workflow

logger = logging.getLogger(__name__)


async def poll_gmail_for_leads() -> None:
    async with get_session() as session:
        tokens: Sequence[GmailToken] = (await session.exec(select(GmailToken))).all()

    for token in tokens:
        try:
            threads = await list_inbox_threads(token.user_id)
        except Exception as exc:
            monitoring.capture_exception(exc)
            continue
        if not threads:
            continue

        new_leads: list[tuple[int, str]] = []
        async with get_session() as session:
            new_leads.clear()
            for thread in threads:
                existing = (
                    await session.exec(
                        select(GmailThread).where(
                            GmailThread.user_id == token.user_id,
                            GmailThread.thread_id == thread["id"],
                        )
                    )
                ).first()
                if existing:
                    continue

                message_text = (thread.get("message") or "").strip()
                if not message_text:
                    message_text = thread.get("snippet", "")
                name = thread.get("from_name") or thread.get("from_email") or "New Lead"
                email = thread.get("from_email") or "unknown@example.com"

                org_id = token.org_id or None
                if not org_id:
                    owner = await session.get(User, token.user_id)
                    org_id = owner.org_id if owner and owner.org_id else None
                if not org_id:
                    logger.warning(
                        "Skipping Gmail thread %s for user %s: missing org context",
                        thread.get("id"),
                        token.user_id,
                    )
                    continue
                lead = Lead(
                    user_id=token.user_id,
                    org_id=org_id,
                    name=name,
                    email=email,
                    message=message_text,
                    score=0.0,
                )
                session.add(lead)
                await session.flush()
                session.add(
                    GmailThread(
                        user_id=token.user_id,
                        org_id=org_id,
                        thread_id=thread["id"],
                        snippet=thread.get("snippet"),
                    )
                )
                new_leads.append((lead.id, org_id))
            await session.commit()
        for lead_id, org_id in new_leads:
            try:
                await Workflow(lead_id, token.user_id, org_id).run()
            except Exception as exc:  # pragma: no cover - defensive
                monitoring.capture_exception(exc)
