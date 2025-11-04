import os
from functools import lru_cache

from backend import monitoring

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - OpenAI optional dependency
    OpenAI = None  # type: ignore[assignment]


def _fallback(name: str, message: str) -> str:
    summary = message.strip() or "No additional context provided."
    return (
        f"Hi {name or 'there'},\n\n"
        "Thanks for reaching out to FreeAgent. Here's a quick proposal based on what you've shared:\n\n"
        f"Summary of your request:\n{summary}\n\n"
        "Scope:\n"
        "- Kickoff session to confirm goals and success metrics.\n"
        "- Implement a focused MVP addressing the top priority.\n"
        "- Provide documentation and walkthrough at handoff.\n\n"
        "Timeline: 2-4 weeks with weekly progress check-ins.\n"
        "Investment: Fixed project fee with milestone-based bonus for hitting stretch goals.\n\n"
        "Let me know if you have questions or adjustments. Once you approve, I'll send a formal agreement.\n\n"
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


def draft(name: str, message: str) -> str:
    client = _get_client()
    if not client:
        return _fallback(name, message)

    prompt = (
        "Write a concise proposal email for a potential client based on their inquiry. "
        "First include a 2 sentence summary of their goals, then bullet the scope, timeline, pricing guidance, "
        "and clear next steps. Maintain a friendly, professional tone.\n\n"
        f"Prospect name: {name or 'there'}\n"
        f"Inquiry:\n{message}"
    )

    try:
        response = client.responses.create(model="gpt-4o-mini", input=prompt)
        text = response.output_text.strip()
        if text:
            return text
    except Exception as exc:
        monitoring.capture_exception(exc)

    return _fallback(name, message)
