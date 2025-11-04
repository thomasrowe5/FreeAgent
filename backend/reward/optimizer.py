import json
import logging
import math
import os
import re
from collections import Counter, deque
from pathlib import Path
from typing import Any, Deque, Dict, Iterable, List, Optional

from backend import monitoring

try:  # optional dependency
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None  # type: ignore[assignment]


logger = logging.getLogger("reward.optimizer")

FEEDBACK_PATH = Path("data/feedback.jsonl")
PROMPTS_DIR = Path("backend/agents/prompts")
OUTPUT_DIR = Path("data/optimized_prompts")


class RewardOptimizer:
    def __init__(self, feedback_path: Path = FEEDBACK_PATH):
        self.feedback_path = feedback_path
        self._client = None

    def run(self) -> Dict[str, Any]:
        records = self._load_feedback()
        if not records:
            logger.info("No feedback records found; skipping optimization")
            return {"optimized": False, "agents": {}}
        metrics = self._compute_metrics(records)
        results: Dict[str, Any] = {}
        for agent, data in metrics.items():
            base_prompt = self._load_prompt(agent)
            optimized_prompt = self._rewrite_prompt(agent, base_prompt, data)
            self._save_prompt(agent, optimized_prompt)
            results[agent] = {
                "acceptance_rate": data["acceptance_rate"],
                "avg_rating": data["avg_rating"],
                "rolling_reward": data["rolling_reward"],
                "top_phrases": data["top_phrases"],
                "output_path": str(self._output_path(agent)),
            }
        return {"optimized": True, "agents": results}

    def _load_feedback(self) -> List[Dict[str, Any]]:
        if not self.feedback_path.exists():
            return []
        records: List[Dict[str, Any]] = []
        with self.feedback_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    records.append(record)
                except json.JSONDecodeError:
                    continue
        return records

    def _compute_metrics(self, records: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        stats: Dict[str, Dict[str, Any]] = {}
        for record in records:
            agent = record.get("metadata", {}).get("agent") or record.get("agent") or "proposal_gen"
            agent_stats = stats.setdefault(
                agent,
                {
                    "total": 0,
                    "accepted": 0,
                    "ratings": [],
                    "rewards": deque(maxlen=50),  # type: Deque[float]
                    "phrases": Counter(),
                },
            )
            agent_stats["total"] += 1
            if self._is_accept(record):
                agent_stats["accepted"] += 1
            rating = self._extract_rating(record)
            if rating is not None:
                agent_stats["ratings"].append(rating)
            reward = self._extract_reward(record)
            agent_stats["rewards"].append(reward)
            text = self._extract_text(record)
            if text:
                agent_stats["phrases"].update(self._keyword_ngrams(text))

        metrics: Dict[str, Dict[str, Any]] = {}
        for agent, data in stats.items():
            total = data["total"] or 1
            acceptance_rate = data["accepted"] / total
            avg_rating = sum(data["ratings"]) / len(data["ratings"]) if data["ratings"] else 0.0
            rolling_reward = sum(data["rewards"]) / len(data["rewards"]) if data["rewards"] else 0.0
            top_phrases = [phrase for phrase, _ in data["phrases"].most_common(5)]
            metrics[agent] = {
                "acceptance_rate": round(acceptance_rate, 4),
                "avg_rating": round(avg_rating, 3),
                "rolling_reward": round(rolling_reward, 4),
                "top_phrases": top_phrases,
            }
        return metrics

    @staticmethod
    def _is_accept(record: Dict[str, Any]) -> bool:
        metadata = record.get("metadata") or {}
        if "label" in record:
            try:
                return float(record["label"]) >= 0.5
            except (TypeError, ValueError):
                pass
        outcome = metadata.get("outcome") or record.get("outcome") or ""
        status = metadata.get("status") or record.get("status") or ""
        text = f"{outcome} {status}".lower()
        positive_terms = ("accept", "approved", "positive", "good", "won", "closed-won")
        negative_terms = ("reject", "decline", "negative", "bad", "lost")
        if any(term in text for term in positive_terms):
            return True
        if any(term in text for term in negative_terms):
            return False
        return bool(metadata.get("accepted", False))

    @staticmethod
    def _extract_rating(record: Dict[str, Any]) -> Optional[float]:
        metadata = record.get("metadata") or {}
        for key in ("rating", "score", "reward"):
            value = metadata.get(key) or record.get(key)
            if value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    continue
        comment = (record.get("comment") or "").lower()
        if "great" in comment:
            return 0.9
        if "bad" in comment:
            return 0.2
        return None

    @staticmethod
    def _extract_reward(record: Dict[str, Any]) -> float:
        metadata = record.get("metadata") or {}
        reward = metadata.get("reward") or record.get("reward")
        if reward is not None:
            try:
                return float(reward)
            except (TypeError, ValueError):
                pass
        return 0.5

    @staticmethod
    def _extract_text(record: Dict[str, Any]) -> str:
        for key in ("text", "prompt", "comment", "input"):
            value = record.get(key)
            if isinstance(value, str) and value.strip():
                return value
        metadata = record.get("metadata") or {}
        for key in ("text", "comment", "summary"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return ""

    @staticmethod
    def _keyword_ngrams(text: str) -> Counter:
        tokens = [token for token in re.findall(r"[A-Za-z0-9]{3,}", text.lower()) if token not in {"the", "and", "for"}]
        counter: Counter = Counter(tokens)
        for i in range(len(tokens) - 1):
            bigram = f"{tokens[i]} {tokens[i+1]}"
            counter[bigram] += 1
        return counter

    def _load_prompt(self, agent: str) -> str:
        prompt_path = PROMPTS_DIR / f"{agent}.txt"
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
        return (
            "You are an autonomous agent supporting FreeAgent operations. "
            "Respond clearly, focus on ROI, and tailor insights to the lead's context."
        )

    def _save_prompt(self, agent: str, prompt: str) -> None:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        path = self._output_path(agent)
        path.write_text(prompt, encoding="utf-8")
        logger.info("Optimized prompt saved", extra={"optimizer": {"agent": agent, "path": str(path)}})

    @staticmethod
    def _output_path(agent: str) -> Path:
        return OUTPUT_DIR / f"{agent}.txt"

    def _rewrite_prompt(self, agent: str, prompt: str, metrics: Dict[str, Any]) -> str:
        bias_block = self._construct_bias(metrics)
        if not bias_block:
            return prompt
        new_prompt = self._call_llm(agent, prompt, bias_block)
        if not new_prompt:
            new_prompt = f"{prompt.strip()}\n\n# Optimization Notes\n{bias_block}"
        return new_prompt

    @staticmethod
    def _construct_bias(metrics: Dict[str, Any]) -> str:
        phrases = metrics.get("top_phrases") or []
        if not phrases:
            return ""
        acceptance = metrics.get("acceptance_rate", 0.0)
        reward = metrics.get("rolling_reward", 0.0)
        bias_lines = [
            f"Acceptance rate: {acceptance:.2%}",
            f"Rolling reward: {reward:.2f}",
            "Key phrases to amplify:",
        ]
        for phrase in phrases:
            weight = max(1, int(math.ceil(acceptance * 5)))
            bias_lines.append(f"- (weight {weight}) {phrase}")
        return "\n".join(bias_lines)

    def _call_llm(self, agent: str, prompt: str, bias_block: str) -> Optional[str]:
        client = self._openai_client()
        if not client:
            return None
        instruction = (
            "You are optimizing an internal system prompt. "
            "Rewrite the prompt to emphasize the weighted phrases while keeping core guidance. "
            "Keep the tone professional and concise."
        )
        template = (
            f"{instruction}\n\nCurrent prompt:\n{prompt}\n\nMetrics:\n{bias_block}\n\n"
            "Return ONLY the rewritten prompt text."
        )
        try:
            response = client.responses.create(model=os.getenv("OPTIMIZER_MODEL", "gpt-4o-mini"), input=template)
            return response.output_text.strip()
        except Exception as exc:  # pragma: no cover
            monitoring.capture_exception(exc)
            logger.warning("LLM rewrite failed for %s: %s", agent, exc)
            return None

    def _openai_client(self):
        if self._client is not None:
            return self._client
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key and OpenAI is not None:
            try:
                self._client = OpenAI(api_key=api_key)
            except Exception as exc:  # pragma: no cover
                monitoring.capture_exception(exc)
                logger.warning("Failed to initialize OpenAI client: %s", exc)
                self._client = None
        return self._client


optimizer = RewardOptimizer()
