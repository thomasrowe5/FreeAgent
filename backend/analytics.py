from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select

from backend.db import AnalyticsSnapshot, GmailToken, Lead, Run, get_session


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _apply_status_defaults(status_breakdown: Dict[str, int]) -> Dict[str, int]:
    for key in ["new", "proposal_sent", "followup_pending", "won", "lost"]:
        status_breakdown.setdefault(key, 0)
    return status_breakdown


async def fetch_metrics(
    user_id: str,
    *,
    start: Optional[str] = None,
    end: Optional[str] = None,
    client_type: Optional[str] = None,
) -> Dict[str, Any]:
    start_dt = _parse_date(start)
    end_dt = _parse_date(end)

    async with get_session() as session:
        lead_stmt = select(Lead).where(Lead.user_id == user_id)
        if client_type and client_type.lower() != "all":
            lead_stmt = lead_stmt.where(Lead.client_type == client_type)
        if start_dt:
            lead_stmt = lead_stmt.where(Lead.created_at >= start_dt)
        if end_dt:
            lead_stmt = lead_stmt.where(Lead.created_at <= end_dt)

        leads = (await session.exec(lead_stmt)).all()
        total_leads = len(leads)

        lead_ids = [lead.id for lead in leads if lead.id is not None]

        status_breakdown: Dict[str, int] = {}
        revenue_total = 0.0
        revenue_by_month: Dict[str, float] = {}
        for lead in leads:
            status_breakdown[lead.status] = status_breakdown.get(lead.status, 0) + 1
            if lead.status == "won" and lead.value:
                revenue_total += float(lead.value)
                month_key = lead.created_at.strftime("%Y-%m") if lead.created_at else "unknown"
                revenue_by_month[month_key] = revenue_by_month.get(month_key, 0.0) + float(lead.value)

        status_breakdown = _apply_status_defaults(status_breakdown)
        wins = status_breakdown.get("won", 0)

        proposals_sent = 0
        followups_sent = 0
        if lead_ids:
            proposal_stmt = select(func.count()).select_from(Run).where(
                Run.kind == "proposal", Run.lead_id.in_(lead_ids)
            )
            followup_stmt = select(func.count()).select_from(Run).where(
                Run.kind == "followup", Run.lead_id.in_(lead_ids)
            )
            if start_dt:
                proposal_stmt = proposal_stmt.where(Run.created_at >= start_dt)
                followup_stmt = followup_stmt.where(Run.created_at >= start_dt)
            if end_dt:
                proposal_stmt = proposal_stmt.where(Run.created_at <= end_dt)
                followup_stmt = followup_stmt.where(Run.created_at <= end_dt)

            proposals_sent = int(await session.scalar(proposal_stmt) or 0)
            followups_sent = int(await session.scalar(followup_stmt) or 0)

        conversion_rate = wins / proposals_sent if proposals_sent else 0.0

    revenue_series = [
        {"month": month, "revenue": round(amount, 2)}
        for month, amount in sorted(revenue_by_month.items())
    ]

    return {
        "leads": total_leads,
        "proposals": proposals_sent,
        "followups": followups_sent,
        "wins": wins,
        "revenue": round(revenue_total, 2),
        "conversion_rate": round(conversion_rate, 4),
        "status_breakdown": status_breakdown,
        "revenue_by_month": revenue_series,
        "filters": {
            "start": start_dt.isoformat() if start_dt else None,
            "end": end_dt.isoformat() if end_dt else None,
            "client_type": client_type or None,
        },
    }


async def get_user_summary(
    user_id: str,
    *,
    start: Optional[str] = None,
    end: Optional[str] = None,
    client_type: Optional[str] = None,
) -> Dict[str, Any]:
    metrics = await fetch_metrics(user_id, start=start, end=end, client_type=client_type)

    async with get_session() as session:
        recent_snapshots = (
            await session.execute(
                select(AnalyticsSnapshot)
                .where(AnalyticsSnapshot.user_id == user_id)
                .order_by(AnalyticsSnapshot.ts.desc())
                .limit(30)
            )
        ).scalars().all()

    metrics["snapshots"] = [
        {
            "ts": snapshot.ts.isoformat() if snapshot.ts else None,
            "total_leads": snapshot.total_leads,
            "proposals_sent": snapshot.proposals_sent,
            "followups_sent": snapshot.followups_sent,
            "wins": snapshot.wins,
            "revenue": snapshot.revenue,
        }
        for snapshot in recent_snapshots
    ]
    return metrics


async def recompute_snapshot_for_user(user_id: str) -> Dict[str, Any]:
    metrics = await fetch_metrics(user_id)
    async with get_session() as session:
        snapshot = AnalyticsSnapshot(
            user_id=user_id,
            total_leads=metrics["leads"],
            proposals_sent=metrics["proposals"],
            followups_sent=metrics["followups"],
            wins=metrics["wins"],
            revenue=metrics["revenue"],
            ts=datetime.utcnow(),
        )
        session.add(snapshot)
        await session.commit()
    return metrics


async def recompute_all_snapshots() -> None:
    async with get_session() as session:
        lead_users = (await session.execute(select(Lead.user_id).distinct())).all()
        token_users = (await session.execute(select(GmailToken.user_id).distinct())).all()

    user_ids = {user_id for (user_id,) in lead_users + token_users if user_id}

    for user_id in user_ids:
        await recompute_snapshot_for_user(user_id)
