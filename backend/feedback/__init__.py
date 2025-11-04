import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlmodel import select

from backend.db import Feedback, get_session
from backend.feedback.loop import feedback_loop

logger = logging.getLogger("feedback")


async def save_feedback(
    *,
    user_id: str,
    org_id: Optional[str],
    lead_id: Optional[int],
    feedback_type: str,
    comment: Optional[str],
    edited_text: Optional[str],
) -> Feedback:
    entry = Feedback(
        user_id=user_id,
        org_id=org_id,
        lead_id=lead_id,
        type=feedback_type,
        comment=comment,
        edited_text=edited_text,
        timestamp=datetime.utcnow(),
    )
    async with get_session() as session:
        session.add(entry)
        await session.commit()
        await session.refresh(entry)
    feedback_loop.mark_dirty()
    logger.info(
        "feedback_saved",
        extra={
            "feedback": {
                "user_id": user_id,
                "lead_id": lead_id,
                "type": feedback_type,
            }
        },
    )
    return entry


async def aggregate_feedback(user_id: str, org_id: Optional[str], limit: int = 5) -> List[Dict[str, int]]:
    async with get_session() as session:
        rows = (
            await session.exec(
                select(Feedback.type, func.count())
                .where(Feedback.user_id == user_id, Feedback.org_id == org_id)
                .group_by(Feedback.type)
                .order_by(func.count().desc())
                .limit(limit)
            )
        ).all()
    return [{"type": type_, "count": int(count)} for type_, count in rows]


async def analyze_feedback(limit: int = 50) -> None:
    async with get_session() as session:
        rows = (
            await session.exec(
                select(Feedback.type, func.count())
                .group_by(Feedback.type)
                .order_by(func.count().desc())
                .limit(limit)
            )
        ).all()
    if not rows:
        logger.info("feedback_analysis", extra={"feedback": {"message": "No feedback to analyze"}})
        return
    summary = {type_: int(count) for type_, count in rows}
    logger.info("feedback_analysis", extra={"feedback": {"summary": summary}})


async def export_dataset(org_id: Optional[str] = None):
    return await feedback_loop.export_dataset(org_id=org_id)


async def insights(org_id: Optional[str]) -> Dict[str, Any]:
    return await feedback_loop.insights(org_id)
