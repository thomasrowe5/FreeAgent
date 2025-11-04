import os
from typing import Any, Dict, List

import httpx

from backend import monitoring


NOTION_API_URL = "https://api.notion.com/v1/databases/{database_id}/query"
DEFAULT_TIMEOUT = float(os.getenv("NOTION_TIMEOUT_SECONDS", "10"))
NOTION_VERSION = os.getenv("NOTION_VERSION", "2022-06-28")


def _token() -> str:
    token = os.getenv("NOTION_API_TOKEN")
    if not token:
        raise RuntimeError("Notion API token not configured")
    return token


def is_configured() -> bool:
    return bool(os.getenv("NOTION_API_TOKEN"))


async def fetch_recent_pages(database_id: str, limit: int = 10) -> List[Dict[str, Any]]:
    token = _token()
    url = NOTION_API_URL.format(database_id=database_id)
    payload: Dict[str, Any] = {"page_size": limit}
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        response = await client.post(url, json=payload, headers=headers)
    try:
        response.raise_for_status()
        data = response.json()
    except Exception as exc:  # pragma: no cover - defensive
        monitoring.capture_exception(exc)
        raise RuntimeError(f"Notion request failed: {exc}") from exc

    results = data.get("results", [])
    formatted = []
    for item in results:
        properties = item.get("properties", {})
        title_prop = properties.get("Name") or properties.get("Title") or {}
        title = ""
        if "title" in title_prop:
            title_parts = title_prop.get("title", [])
            if title_parts:
                title = "".join(part.get("plain_text", "") for part in title_parts)
        formatted.append(
            {
                "id": item.get("id"),
                "url": item.get("url"),
                "last_edited_time": item.get("last_edited_time"),
                "title": title,
            }
        )
    return formatted
