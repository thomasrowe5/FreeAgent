import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy import func
from sqlmodel import select

from backend.db import Feedback, get_session

logger = logging.getLogger("feedback")


async def save_feedback(
    *,
    user_id: str,
    lead_id: Optional[int],
    feedback_type: str,
    comment: Optional[str],
    edited_text: Optional[str],
) -> Feedback:
    entry = Feedback(
        user_id=user_id,
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


async def aggregate_feedback(user_id: str, limit: int = 5) -> List[Dict[str, int]]:
    async with get_session() as session:
        rows = (
            await session.exec(
                select(Feedback.type, func.count())
                .where(Feedback.user_id == user_id)
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


async def export_dataset(path: Path) -> int:
    async with get_session() as session:
        entries = (
            await session.exec(select(Feedback).order_by(Feedback.timestamp.asc()))
        ).all()
    if not entries:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for entry in entries:
            record = {
                "prompt": entry.comment or "",
                "completion": entry.edited_text or "",
                "metadata": {
                    "user_id": entry.user_id,
                    "lead_id": entry.lead_id,
                    "type": entry.type,
                    "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
                },
            }
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return len(entries)
