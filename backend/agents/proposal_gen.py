"""Proposal generation utilities for FreeAgent delivery workflows."""

import os
from functools import lru_cache
from typing import Iterable, List, Optional

from backend import monitoring
from backend.feedback.loop import feedback_loop

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - OpenAI optional dependency
    OpenAI = None  # type: ignore[assignment]


def _format_memories(memories: Optional[Iterable[dict]]) -> str:
    if not memories:
        return ""
    lines = []
    for item in memories[:5]:
        value = item.get("value") or ""
        lines.append(f"- {value.strip()}")
    return "\n".join(lines)


def _format_vector_context(context: Optional[Iterable[dict]]) -> str:
    if not context:
        return ""
    lines = []
    for item in context:
        meta = item.get("metadata") or {}
        outcome = meta.get("outcome")
        text = (item.get("text") or "").strip().replace("\n", " ")
        snippet = text[:280]
        if len(text) > 280:
            snippet += "..."
        label = meta.get("lead_name") or meta.get("lead_id") or "Lead"
        if outcome:
            lines.append(f"- {label}: {snippet} | Outcome: {outcome}")
        else:
            lines.append(f"- {label}: {snippet}")
    return "\n".join(lines)


def _fallback(
    name: str,
    message: str,
    memories: Optional[Iterable[dict]] = None,
    vector_context: Optional[Iterable[dict]] = None,
) -> str:
    summary = message.strip() or "No additional context provided."
    memory_text = _format_memories(memories)
    context_text = _format_vector_context(vector_context)
    parts = [
        f"Hi {name or 'there'},\n\n",
        "Thanks for reaching out to FreeAgent. Here's a quick proposal based on what you've shared:\n\n",
        f"Summary of your request:\n{summary}\n\n",
    ]
    if memory_text:
        parts.append(f"Recent project context:\n{memory_text}\n\n")
    if context_text:
        parts.append(f"Similar engagements:\n{context_text}\n\n")
    parts.extend(
        [
            "Scope:\n",
            "- Kickoff session to confirm goals and success metrics.\n",
            "- Implement a focused MVP addressing the top priority.\n",
            "- Provide documentation and walkthrough at handoff.\n\n",
            "Timeline: 2-4 weeks with weekly progress check-ins.\n",
            "Investment: Fixed project fee with milestone-based bonus for hitting stretch goals.\n\n",
            "Let me know if you have questions or adjustments. Once you approve, I'll send a formal agreement.\n\n",
            "- FreeAgent",
        ]
    )
    bias = feedback_loop.get_prompt_bias("proposal")
    if bias:
        parts.insert(0, f"{bias.strip()}\n\n")
    return "".join(parts)


@lru_cache(maxsize=1)
def _get_client():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or OpenAI is None:
        return None
    try:
        return OpenAI(api_key=api_key)
    except Exception:
        return None


def draft(name: str, message: str, memories: Optional[List[dict]] = None) -> str:
    """Generate a proposal using memory-aware context (no vector recall).

    Args:
        name: Prospect name or company.
        message: The original inquiry text.
        memories: Optional list of structured memory entries.

    Returns:
        str: A proposal email body.
    """
    return draft_with_context(name, message, memories=memories, vector_context=None)


def draft_with_context(
    name: str,
    message: str,
    memories: Optional[Iterable[dict]] = None,
    vector_context: Optional[Iterable[dict]] = None,
) -> str:
    """Generate a proposal with vector memory context and tone biasing.

    Args:
        name: Prospect name or company.
        message: The original inquiry text.
        memories: Structured memory entries (key/value format).
        vector_context: Similar interactions retrieved from vector memory.

    Returns:
        str: A proposal email body tailored to the client.
    """
    client = _get_client()
    if not client:
        return _fallback(name, message, memories, vector_context)

    prompt = (
        "Write a concise proposal email for a potential client based on their inquiry. "
        "First include a 2 sentence summary of their goals, then bullet the scope, timeline, pricing guidance, "
        "and clear next steps. Maintain a friendly, professional tone.\n\n"
        f"Prospect name: {name or 'there'}\n"
        f"Inquiry:\n{message}"
    )
    memory_text = _format_memories(memories)
    if memory_text:
        prompt += f"\n\nRelevant project memories:\n{memory_text}"
    context_text = _format_vector_context(vector_context)
    if context_text:
        prompt += f"\n\nSimilar engagements and outcomes:\n{context_text}"

    bias = feedback_loop.get_prompt_bias("proposal")
    if bias:
        prompt = f"{bias.strip()}\n\n{prompt}"

    try:
        response = client.responses.create(model="gpt-4o-mini", input=prompt)
        text = response.output_text.strip()
        if text:
            return text
    except Exception as exc:
        monitoring.capture_exception(exc)

    return _fallback(name, message, memories, vector_context)
