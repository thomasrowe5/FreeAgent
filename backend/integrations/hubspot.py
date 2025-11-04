import os
from typing import Any, Dict

import httpx

from backend import monitoring


HUBSPOT_API_URL = "https://api.hubapi.com/crm/v3/objects/deals"
DEFAULT_TIMEOUT = float(os.getenv("HUBSPOT_TIMEOUT_SECONDS", "10"))


def _token() -> str:
    token = os.getenv("HUBSPOT_PRIVATE_APP_TOKEN")
    if not token:
        raise RuntimeError("HubSpot private app token not configured")
    return token


def is_configured() -> bool:
    return bool(os.getenv("HUBSPOT_PRIVATE_APP_TOKEN"))


def _build_payload(lead_id: int, proposal_status: str) -> Dict[str, Any]:
    properties = {
        "dealname": f"Lead {lead_id} - {proposal_status}",
        "pipeline": os.getenv("HUBSPOT_PIPELINE_ID", "default"),
        "dealstage": os.getenv("HUBSPOT_DEAL_STAGE", "appointmentscheduled"),
        "proposal_status__c": proposal_status,
    }
    return {"properties": properties}


async def push_deal(lead_id: int, proposal_status: str) -> Dict[str, Any]:
    token = _token()
    payload = _build_payload(lead_id, proposal_status)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        response = await client.post(HUBSPOT_API_URL, json=payload, headers=headers)
    try:
        response.raise_for_status()
        data = response.json()
    except Exception as exc:  # pragma: no cover - defensive
        monitoring.capture_exception(exc)
        raise RuntimeError(f"HubSpot request failed: {exc}") from exc

    return data
