import os
from typing import Any, Dict

import httpx

from backend import monitoring


SLACK_API_URL = "https://slack.com/api/chat.postMessage"
DEFAULT_TIMEOUT = float(os.getenv("SLACK_TIMEOUT_SECONDS", "10"))


def _token() -> str:
    token = os.getenv("SLACK_BOT_TOKEN")
    if not token:
        raise RuntimeError("Slack bot token not configured")
    return token


def is_configured() -> bool:
    return bool(os.getenv("SLACK_BOT_TOKEN"))


async def send_message(channel: str, text: str) -> Dict[str, Any]:
    token = _token()
    payload = {"channel": channel, "text": text}
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }

    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        response = await client.post(SLACK_API_URL, json=payload, headers=headers)
    try:
        response.raise_for_status()
        data = response.json()
    except Exception as exc:  # pragma: no cover - safety
        monitoring.capture_exception(exc)
        raise RuntimeError(f"Slack request failed: {exc}") from exc

    if not data.get("ok", False):
        error = data.get("error", "unknown_error")
        raise RuntimeError(f"Slack API error: {error}")
    return data
