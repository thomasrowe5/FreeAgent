import json
import math
import os
from functools import lru_cache
from typing import Optional

from backend import monitoring

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - OpenAI optional dependency
    OpenAI = None  # type: ignore[assignment]


def _fallback_score(message: str) -> float:
    """Deterministic heuristic when LLM is unavailable."""
    text = message.lower()
    base = 0.25
    budget_boost = 0.15 if "budget" in text or "$" in text else 0.0
    intent_keywords = ["timeline", "deadline", "launch", "ship"]
    intent_boost = 0.15 if any(k in text for k in intent_keywords) else 0.0
    urgency_boost = 0.1 if any(k in text for k in ["urgent", "asap", "rush"]) else 0.0
    detail_factor = 0.25 * math.tanh(len(message) / 300)
    score = base + budget_boost + intent_boost + urgency_boost + detail_factor
    return round(max(0.0, min(1.0, score)), 3)


@lru_cache(maxsize=1)
def _get_client() -> Optional["OpenAI"]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or OpenAI is None:
        return None
    try:
        return OpenAI(api_key=api_key)
    except Exception:
        return None


def _extract_score(raw: str) -> Optional[float]:
    raw = raw.strip()
    try:
        data = json.loads(raw)
        score = float(data.get("score"))
        if 0.0 <= score <= 1.0:
            return score
    except Exception:
        pass
    try:
        score = float(raw)
        if 0.0 <= score <= 1.0:
            return score
    except ValueError:
        return None
    return None


def score(name: str, email: str, message: str) -> float:
    client = _get_client()
    if not client:
        return _fallback_score(message)

    prompt = (
        "You classify inbound leads. "
        "Return JSON like {\"score\": 0.0-1.0}. "
        "Score higher when the prospect mentions budget, timeline, or clear intent to start. "
        "Score lower when intent is vague or exploratory.\n\n"
        f"Name: {name}\nEmail: {email}\nMessage: {message}"
    )

    try:
        response = client.responses.create(model="gpt-4o-mini", input=prompt)
        content = response.output_text
        parsed = _extract_score(content)
        if parsed is not None:
            return round(parsed, 3)
    except Exception as exc:
        monitoring.capture_exception(exc)

    return _fallback_score(message)
