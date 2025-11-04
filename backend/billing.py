import os
from datetime import datetime
from typing import Dict, Optional

from sqlalchemy import func
from sqlmodel import select

from backend.db import Organization, Usage, get_session

FREE_PLAN_LIMIT = 20


class UsageLimitExceeded(Exception):
    """Raised when a user exceeds their plan quota."""


def current_month() -> str:
    return datetime.utcnow().strftime("%Y-%m")


async def get_plan(org_id: str) -> Dict[str, Optional[str]]:
    async with get_session() as session:
        org = await session.get(Organization, org_id)
    plan_name = org.plan if org else "free"
    limit = FREE_PLAN_LIMIT if plan_name == "free" else None
    return {
        "name": plan_name,
        "limit": limit,
        "stripe_customer_id": org.stripe_customer_id if org else None,
    }


async def _get_or_create_usage(session, org_id: str, action_type: str, month: str) -> Usage:
    usage = (
        await session.exec(
            select(Usage).where(
                Usage.org_id == org_id,
                Usage.action_type == action_type,
                Usage.month == month,
            )
        )
    ).first()
    if not usage:
        usage = Usage(org_id=org_id, action_type=action_type, month=month, count=0)
        session.add(usage)
        await session.flush()
    return usage


async def increment_usage(org_id: str, action_type: str) -> None:
    month = current_month()
    plan = await get_plan(org_id)
    limit = plan.get("limit", FREE_PLAN_LIMIT)

    async with get_session() as session:
        usage = await _get_or_create_usage(session, org_id, action_type, month)
        usage.count += 1
        session.add(usage)
        await session.flush()

        total = await session.scalar(
            select(func.coalesce(func.sum(Usage.count), 0)).where(
                Usage.org_id == org_id,
                Usage.month == month,
            )
        )

        if total and limit and total > limit:
            await session.rollback()
            raise UsageLimitExceeded("Monthly usage limit reached for the current plan.")

        await session.commit()


async def get_usage(org_id: str) -> Dict[str, Dict[str, int]]:
    month = current_month()
    async with get_session() as session:
        rows = (
            await session.exec(
                select(Usage).where(Usage.org_id == org_id, Usage.month == month)
            )
        ).all()
    breakdown = {row.action_type: row.count for row in rows}
    total = sum(breakdown.values())
    return {"month": month, "total": total, "breakdown": breakdown}


async def get_status(org_id: str) -> Dict[str, Optional[str]]:
    plan = await get_plan(org_id)
    usage = await get_usage(org_id)
    limit = plan.get("limit", FREE_PLAN_LIMIT)
    remaining = max(limit - usage["total"], 0) if limit is not None else None
    return {
        "plan": plan["name"],
        "limit": limit,
        "usage": usage["total"],
        "remaining": remaining,
        "breakdown": usage["breakdown"],
        "month": usage["month"],
    }


async def create_checkout_session(org_id: str) -> str:
    base_url = os.getenv("STRIPE_CHECKOUT_URL", "https://billing.stripe.com/test_checkout")
    plan_param = os.getenv("STRIPE_DEFAULT_PLAN", "pro_monthly")
    return f"{base_url}?prefill={org_id}&plan={plan_param}"
