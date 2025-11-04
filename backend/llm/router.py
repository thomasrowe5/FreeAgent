import hashlib
import json
import logging
import os
import threading
from collections import OrderedDict
from typing import Any, Dict, Optional, Tuple

import httpx

from backend import monitoring

try:  # optional dependency
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None  # type: ignore[assignment]


MODELS = {
    "fast": "gpt-4o-mini",
    "reasoning": "gpt-4o",
    "local": "mistral",
}


logger = logging.getLogger("llm.router")


class LLMRouter:
    """Selects an LLM based on prompt characteristics and caches idempotent responses."""

    def __init__(self, *, cache_size: int = 128) -> None:
        self.cache_size = cache_size
        self._cache: "OrderedDict[str, Tuple[str, Dict[str, Any]]]" = OrderedDict()
        self._cache_lock = threading.Lock()
        self._openai_client = self._init_openai()

    @staticmethod
    def _init_openai() -> Optional["OpenAI"]:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key or OpenAI is None:
            return None
        try:
            return OpenAI(api_key=api_key)
        except Exception as exc:  # pragma: no cover - defensive
            monitoring.capture_exception(exc)
            return None

    def _cache_key(self, prompt: str, context: Optional[Dict[str, Any]]) -> str:
        payload = {
            "prompt": prompt,
            "context": context or {},
        }
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _lookup_cache(self, key: str) -> Optional[Tuple[str, Dict[str, Any]]]:
        with self._cache_lock:
            value = self._cache.get(key)
            if value is not None:
                # move to end to signify recent use
                self._cache.move_to_end(key)
            return value

    def _store_cache(self, key: str, response: str, metadata: Dict[str, Any]) -> None:
        with self._cache_lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = (response, metadata)
            while len(self._cache) > self.cache_size:
                self._cache.popitem(last=False)

    @staticmethod
    def _expected_tokens(context: Optional[Dict[str, Any]]) -> int:
        if not context:
            return 0
        return int(context.get("expected_tokens") or 0)

    def _contains_keywords(self, prompt: str) -> bool:
        lowered = prompt.lower()
        keywords = ("financial", "strategic")
        return any(keyword in lowered for keyword in keywords)

    def _select_model(self, prompt: str, context: Optional[Dict[str, Any]]) -> str:
        prompt_length = len(prompt)
        expected = self._expected_tokens(context)
        model = MODELS["local"]  # default fallback

        if prompt_length < 500 or (expected and expected < 200):
            model = MODELS["fast"]

        if self._contains_keywords(prompt):
            model = MODELS["reasoning"]

        # map anything unknown to local to avoid unexpected failures
        if model not in MODELS.values():
            model = MODELS["local"]
        return model

    def route_and_execute(self, prompt: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Route the prompt to the best-fit model, execute it, and cache the response.

        Returns a payload containing the model name, text output, and whether the cache was hit.
        """
        cache_key = self._cache_key(prompt, context)
        cached = self._lookup_cache(cache_key)
        if cached:
            response, metadata = cached
            return {
                "model": metadata.get("model"),
                "output": response,
                "cached": True,
                **{k: v for k, v in metadata.items() if k != "model"},
            }

        model = self._select_model(prompt, context)
        result_text: str
        metadata: Dict[str, Any] = {"model": model}

        try:
            if model == MODELS["local"]:
                result_text = self._invoke_local_model(prompt, context)
            else:
                result_text = self._invoke_openai_model(model, prompt, context)
        except Exception as exc:  # pragma: no cover - defensive
            monitoring.capture_exception(exc)
            logger.error("LLM execution failed; falling back to local stub", exc_info=exc)
            metadata["error"] = str(exc)
            result_text = self._fallback_response(prompt)
            metadata["model"] = MODELS["local"]

        self._store_cache(cache_key, result_text, metadata)
        return {
            "model": metadata["model"],
            "output": result_text,
            "cached": False,
            **{k: v for k, v in metadata.items() if k not in {"model", "error"}},
            **({"error": metadata["error"]} if "error" in metadata else {}),
        }

    def _invoke_openai_model(
        self,
        model: str,
        prompt: str,
        context: Optional[Dict[str, Any]],
    ) -> str:
        client = self._openai_client
        if not client:
            raise RuntimeError("OPENAI_API_KEY not configured")

        payload_context = json.dumps(context or {}, ensure_ascii=False, sort_keys=True, default=str)
        system_prompt = context.get("system_prompt") if context else None
        if system_prompt:
            final_prompt = f"{system_prompt.strip()}\n\n{prompt}"
        else:
            final_prompt = prompt

        response = client.responses.create(
            model=model,
            input=final_prompt,
            metadata={
                "context": payload_context,
                "router_model": model,
            },
        )
        return response.output_text.strip()

    def _invoke_local_model(self, prompt: str, context: Optional[Dict[str, Any]]) -> str:
        base_url = os.getenv("LOCAL_LLM_URL", "http://localhost:11434/api/generate")
        model = MODELS["local"]
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
        }
        options = context.get("options") if context else None
        if options is not None:
            payload["options"] = options

        with httpx.Client(timeout=float(os.getenv("LLM_ROUTER_TIMEOUT", "15"))) as client:
            response = client.post(base_url, json=payload)
            response.raise_for_status()
            data = response.json()

        if "output" in data:
            return data["output"].strip()
        if "response" in data:
            return data["response"].strip()
        if "text" in data:
            return data["text"].strip()
        return json.dumps(data, ensure_ascii=False)

    @staticmethod
    def _fallback_response(prompt: str) -> str:
        snippet = prompt.strip()
        if len(snippet) > 240:
            snippet = f"{snippet[:237]}..."
        return (
            "LLM processing is currently unavailable. "
            "Here is a truncated echo of your request:\n\n"
            f"{snippet}"
        )


router = LLMRouter()
