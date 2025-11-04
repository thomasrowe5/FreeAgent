import asyncio
import json
import math
import os
from functools import lru_cache
from typing import Any, Dict, List, Optional

from sqlmodel import select

from backend.db import MemoryEntry, get_session

try:  # optional dependency
    from redis import Redis
except ImportError:  # pragma: no cover
    Redis = None  # type: ignore[assignment]

try:  # optional dependency
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None  # type: ignore[assignment]

CACHE_PREFIX = "memory:"


def _connect_redis() -> Optional[Redis]:
    url = os.getenv("REDIS_URL")
    if not url or not Redis:
        return None
    try:
        return Redis.from_url(url)
    except Exception:  # pragma: no cover
        return None


redis_client = _connect_redis()


@lru_cache(maxsize=1)
def _get_openai_client() -> Optional[OpenAI]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or OpenAI is None:
        return None
    try:
        return OpenAI(api_key=api_key)
    except Exception:  # pragma: no cover
        return None


async def _embed_openai(text: str) -> Optional[List[float]]:
    client = _get_openai_client()
    if not client:
        return None
    try:
        response = await asyncio.to_thread(
            client.embeddings.create,
            model=os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small"),
            input=text,
        )
        return list(response.data[0].embedding)  # type: ignore[attr-defined]
    except Exception:
        return None


def _fallback_embed(text: str, dims: int = 64) -> List[float]:
    vec = [0.0] * dims
    for token in text.lower().split():
        idx = hash(token) % dims
        vec[idx] += 1.0
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


async def embed_text(text: str) -> List[float]:
    text = (text or "").strip()
    if not text:
        return [0.0]
    vector = await _embed_openai(text)
    if vector:
        return vector
    return _fallback_embed(text)


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b:
        return 0.0
    size = min(len(a), len(b))
    dot = sum(a[i] * b[i] for i in range(size))
    norm_a = math.sqrt(sum(a[i] * a[i] for i in range(size))) or 1.0
    norm_b = math.sqrt(sum(b[i] * b[i] for i in range(size))) or 1.0
    return dot / (norm_a * norm_b)


async def add_memory(
    *,
    user_id: str,
    org_id: Optional[str],
    key: str,
    value: str,
    payload: Optional[Dict[str, Any]] = None,
    vector: Optional[List[float]] = None,
) -> MemoryEntry:
    if vector is None:
        vector = await embed_text(value)
    entry = MemoryEntry(
        user_id=user_id,
        org_id=org_id,
        key=key,
        value=value,
        payload=payload or {},
        vector=vector,
    )
    async with get_session() as session:
        session.add(entry)
        await session.commit()
        await session.refresh(entry)
    if redis_client:
        redis_client.delete(f"{CACHE_PREFIX}{user_id}:{key}")
    return entry


async def get_memory(user_id: str, org_id: Optional[str], key: str) -> List[MemoryEntry]:
    cache_key = f"{CACHE_PREFIX}{org_id or user_id}:{key}"
    if redis_client:
        cached = redis_client.get(cache_key)
        if cached:
            try:
                data = json.loads(cached)
                return [MemoryEntry.model_validate(item) for item in data]
            except Exception:  # pragma: no cover
                redis_client.delete(cache_key)
    async with get_session() as session:
        entries = (
            await session.exec(
                select(MemoryEntry)
                .where(MemoryEntry.user_id == user_id, MemoryEntry.org_id == org_id, MemoryEntry.key == key)
                .order_by(MemoryEntry.created_at.desc())
            )
        ).all()
    if redis_client:
        redis_client.set(cache_key, json.dumps([entry.model_dump() for entry in entries], default=str), ex=300)
    return entries


async def search_memory(user_id: str, org_id: Optional[str], query: str, limit: int = 5) -> List[Dict[str, Any]]:
    vector = await embed_text(query)
    async with get_session() as session:
        rows = (
            await session.exec(
                select(MemoryEntry)
                .where(MemoryEntry.user_id == user_id, MemoryEntry.org_id == org_id)
                .order_by(MemoryEntry.created_at.desc())
                .limit(200)
            )
        ).all()
    scored = []
    for entry in rows:
        entry_vector = entry.vector or await embed_text(entry.value)
        score = _cosine(vector, entry_vector)
        scored.append(
            {
                "id": entry.id,
                "key": entry.key,
                "value": entry.value,
                "payload": entry.payload,
                "score": score,
            }
        )
    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:limit]
