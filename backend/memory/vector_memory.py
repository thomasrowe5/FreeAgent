import json
import math
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

try:
    import chromadb
    from chromadb.utils import embedding_functions
except ImportError:  # pragma: no cover - optional dependency
    chromadb = None  # type: ignore[assignment]
    embedding_functions = None  # type: ignore[assignment]

DATA_DIR = Path(os.getenv("MEMORY_VECTOR_DIR", "data/memory/chroma")).resolve()
AGENT_COLLECTIONS = {
    "lead_scorer": "memory_lead_scorer",
    "proposal_gen": "memory_proposal_gen",
    "followups": "memory_followups",
}

_client = None
_collections: Dict[str, Any] = {}
_embedding_function = None


class _SimpleEmbeddingFunction:
    """Deterministic hashed embedding fallback when OpenAI is unavailable."""

    def __init__(self, dims: int = 64):
        self.dims = dims

    def __call__(self, texts: List[str]) -> List[List[float]]:
        vectors: List[List[float]] = []
        for text in texts:
            tokens = (text or "").lower().split()
            vec = [0.0] * self.dims
            for token in tokens:
                idx = hash(token) % self.dims
                vec[idx] += 1.0
            norm = math.sqrt(sum(x * x for x in vec)) or 1.0
            vectors.append([x / norm for x in vec])
        return vectors


def _ensure_client():
    global _client
    if _client is not None:
        return _client
    if chromadb is None:
        raise RuntimeError("chromadb is not installed")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _client = chromadb.PersistentClient(path=str(DATA_DIR))
    return _client


def _ensure_embedding_function():
    global _embedding_function
    if _embedding_function is not None:
        return _embedding_function
    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")
    if api_key and embedding_functions is not None:
        _embedding_function = embedding_functions.OpenAIEmbeddingFunction(
            api_key=api_key,
            model_name=model,
        )
    else:
        _embedding_function = _SimpleEmbeddingFunction()
    return _embedding_function


def _collection(agent: str):
    if agent in _collections:
        return _collections[agent]
    client = _ensure_client()
    name = AGENT_COLLECTIONS.get(agent, f"memory_{agent}")
    collection = client.get_or_create_collection(
        name=name,
        embedding_function=_ensure_embedding_function(),
    )
    _collections[agent] = collection
    return collection


def _normalize_lead(lead: Any) -> Dict[str, Any]:
    if lead is None:
        return {}
    if isinstance(lead, dict):
        return lead
    result = {}
    for attr in ("id", "name", "email", "message", "score", "status"):
        value = getattr(lead, attr, None)
        if value is not None:
            result[attr] = value
    return result


def save_interaction(agent: str, lead: Any, text: str, outcome: Any) -> None:
    try:
        collection = _collection(agent)
    except Exception:
        return
    lead_payload = _normalize_lead(lead)
    outcome_text = outcome
    if isinstance(outcome, (dict, list)):
        outcome_text = json.dumps(outcome)
    metadata = {
        "lead_id": lead_payload.get("id"),
        "lead_name": lead_payload.get("name"),
        "outcome": outcome_text,
        "timestamp": datetime.utcnow().isoformat(),
    }
    document = text or outcome_text or ""
    if lead_payload.get("message"):
        metadata["lead_message"] = lead_payload["message"]
    doc_id = uuid4().hex
    try:
        collection.add(
            ids=[doc_id],
            documents=[document],
            metadatas=[metadata],
        )
    except Exception:
        # best effort only
        pass


def retrieve_context(agent: str, query: str, k: int = 3) -> List[Dict[str, Any]]:
    if not query:
        return []
    try:
        collection = _collection(agent)
    except Exception:
        return []
    try:
        response = collection.query(
            query_texts=[query],
            n_results=k,
            include=["documents", "metadatas", "distances"],
        )
    except Exception:
        return []
    documents = response.get("documents") or [[]]
    metadatas = response.get("metadatas") or [[]]
    distances = response.get("distances") or [[]]
    results: List[Dict[str, Any]] = []
    for doc, meta, dist in zip(documents[0], metadatas[0], distances[0]):
        results.append(
            {
                "text": doc,
                "metadata": meta,
                "score": dist,
            }
        )
    return results


def get_recent(agent: str, limit: int = 10) -> List[Dict[str, Any]]:
    try:
        collection = _collection(agent)
    except Exception:
        return []
    try:
        data = collection.get(include=["documents", "metadatas", "ids"])
    except Exception:
        return []
    documents = data.get("documents", [])
    metadatas = data.get("metadatas", [])
    ids = data.get("ids", [])
    items: List[Dict[str, Any]] = []
    for doc_id, doc, meta in zip(ids, documents, metadatas):
        timestamp = meta.get("timestamp") if isinstance(meta, dict) else None
        items.append(
            {
                "id": doc_id,
                "text": doc,
                "metadata": meta,
                "timestamp": timestamp,
            }
        )
    items.sort(key=lambda item: item.get("timestamp") or "", reverse=True)
    return items[:limit]
