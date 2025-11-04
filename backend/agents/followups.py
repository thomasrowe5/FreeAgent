import os
from functools import lru_cache

from backend import monitoring

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - OpenAI optional dependency
    OpenAI = None  # type: ignore[assignment]


def _fallback(name: str, days_after: int, last_message: str) -> str:
    return (
        f"Hi {name or 'there'},\n\n"
        f"Hope you're well. I wanted to check in since it's been about {days_after} days "
        "since we shared the proposal. Happy to adjust scope or timelines "
        "based on the details you mentioned:\n"
        f"{last_message.strip() or 'No additional context provided.'}\n\n"
        "Let me know what feels like the right next step.\n\n"
        "- FreeAgent"
    )


@lru_cache(maxsize=1)
def _get_client():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or OpenAI is None:
        return None
    try:
        return OpenAI(api_key=api_key)
    except Exception:
        return None


def compose(name: str, days_after: int, last_message: str = "") -> str:
    client = _get_client()
    if not client:
        return _fallback(name, days_after, last_message)

    prompt = (
        "Draft a friendly follow-up email to a prospect after sending a proposal. "
        "Reference the original request, offer to adjust scope or timing, and keep it under 180 words.\n\n"
        f"Prospect name: {name or 'there'}\n"
        f"Days since proposal sent: {days_after}\n"
        f"Original inquiry details:\n{last_message}"
    )

    try:
        response = client.responses.create(model="gpt-4o-mini", input=prompt)
        text = response.output_text.strip()
        if text:
            return text
    except Exception as exc:
        monitoring.capture_exception(exc)

    return _fallback(name, days_after, last_message)
