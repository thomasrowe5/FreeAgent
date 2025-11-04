from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlmodel import select

from backend import monitoring
from backend.db import Feedback, Lead, Proposal, get_session

TRAINING_DIR = Path(os.getenv("TRAINING_DATA_DIR", "data"))
TRAINING_PATH = TRAINING_DIR / "training.jsonl"

POSITIVE_HINTS = ("accept", "approve", "approved", "positive", "great", "love", "good", "ship")
NEGATIVE_HINTS = ("reject", "decline", "negative", "bad", "issue", "problem", "redo", "fail")
AGENT_PATTERN = re.compile(r"(?:agent[:=]\s*)([A-Za-z0-9_\-]+)", re.IGNORECASE)


@dataclass
class Sample:
    prompt: str
    input_text: str
    output_text: str
    label: int
    agent: str
    metadata: Dict[str, Any]


class RewardModel:
    """Tiny logistic regression classifier for feedback acceptance."""

    def __init__(self, *, learning_rate: float = 0.15, epochs: int = 120, l2: float = 1e-4) -> None:
        self.learning_rate = learning_rate
        self.epochs = epochs
        self.l2 = l2
        self.weights: Dict[str, float] = defaultdict(float)
        self.bias: float = 0.0
        self.is_trained: bool = False

    @staticmethod
    def _tokenize(text: str) -> Counter[str]:
        words = re.findall(r"[A-Za-z0-9]+", text.lower())
        return Counter(words)

    def _featurize(self, prompt: str, input_text: str, output_text: str) -> Counter[str]:
        combined = f"{prompt}\n{input_text}\n{output_text}"
        return self._tokenize(combined)

    @staticmethod
    def _sigmoid(value: float) -> float:
        # Guard against overflow
        if value < -50:
            return 0.0
        if value > 50:
            return 1.0
        return 1.0 / (1.0 + math.exp(-value))

    def reset(self) -> None:
        self.weights = defaultdict(float)
        self.bias = 0.0
        self.is_trained = False

    def train(self, samples: List[Sample]) -> None:
        if not samples:
            self.reset()
            return

        # Initialize weights
        for sample in samples:
            features = self._featurize(sample.prompt, sample.input_text, sample.output_text)
            for token in features:
                _ = self.weights[token]  # ensure key exists

        for _ in range(self.epochs):
            for sample in samples:
                features = self._featurize(sample.prompt, sample.input_text, sample.output_text)
                activation = self.bias
                for token, count in features.items():
                    activation += self.weights[token] * count
                prediction = self._sigmoid(activation)
                error = prediction - sample.label

                # Update bias
                self.bias -= self.learning_rate * error

                # Update weights with L2 penalty
                for token, count in features.items():
                    gradient = error * count + self.l2 * self.weights[token]
                    self.weights[token] -= self.learning_rate * gradient

        self.is_trained = True

    def predict(self, prompt: str, input_text: str, output_text: str) -> float:
        if not self.is_trained or not self.weights:
            return 0.5
        features = self._featurize(prompt, input_text, output_text)
        activation = self.bias
        for token, count in features.items():
            activation += self.weights.get(token, 0.0) * count
        return self._sigmoid(activation)


class FeedbackLoop:
    """Coordinates dataset export, reward modelling, and prompt biasing."""

    def __init__(self) -> None:
        self.training_path = TRAINING_PATH
        self._lock = asyncio.Lock()
        self.reward_model = RewardModel()
        self._trained_sample_count = 0
        self._dirty = True
        self._agent_stats: Dict[str, Dict[str, float]] = defaultdict(
            lambda: {"avg": 0.5, "count": 0.0, "last": 0.5}
        )
        self._last_export_path: Optional[Path] = None
        self._last_fine_tune_job: Optional[str] = None
        self._logger = logging.getLogger("feedback.loop")

    def mark_dirty(self) -> None:
        self._dirty = True

    def last_export_path(self) -> Optional[Path]:
        return self._last_export_path

    async def export_dataset(self, org_id: Optional[str] = None) -> Tuple[int, Path]:
        async with self._lock:
            samples = await self._collect_samples(org_id=org_id)
            export_path = self._export_path_for_org(org_id)
            if not samples:
                self._last_export_path = export_path
                return 0, export_path
            export_path.parent.mkdir(parents=True, exist_ok=True)
            with export_path.open("w", encoding="utf-8") as handle:
                for sample in samples:
                    record = {
                        "prompt": sample.prompt,
                        "input": sample.input_text,
                        "output": sample.output_text,
                        "label": sample.label,
                        "metadata": sample.metadata,
                    }
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._last_export_path = export_path
            return len(samples), export_path

    async def ensure_trained(self) -> None:
        async with self._lock:
            if not self._dirty and self.reward_model.is_trained:
                return
            samples = await self._collect_samples(org_id=None)
            if not samples:
                self.reward_model.reset()
                self._trained_sample_count = 0
                self._dirty = False
                return
            self.training_path.parent.mkdir(parents=True, exist_ok=True)
            with self.training_path.open("w", encoding="utf-8") as handle:
                for sample in samples:
                    record = {
                        "prompt": sample.prompt,
                        "input": sample.input_text,
                        "output": sample.output_text,
                        "label": sample.label,
                        "metadata": sample.metadata,
                    }
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            self.reward_model.train(samples)
            self._trained_sample_count = len(samples)
            self._dirty = False
            if os.getenv("ENABLE_FEEDBACK_FINE_TUNE") == "1":
                await self._maybe_schedule_finetune()

    async def score_generation(
        self,
        agent: str,
        prompt: str,
        output_text: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> float:
        await self.ensure_trained()
        input_text = ""
        if context:
            input_text = context.get("feedback") or context.get("comment") or ""
        score = self.reward_model.predict(prompt, input_text, output_text)
        self._update_agent_stats(agent, score)
        return score

    def get_prompt_bias(self, agent: str) -> str:
        stats = self._agent_stats.get(agent)
        if not stats:
            return ""
        avg = stats["avg"]
        if avg < 0.35:
            return (
                "System reminder: Recent feedback indicates low satisfaction. "
                "Prioritize clarity, concrete next steps, and ensure the tone is proactive and reassuring."
            )
        if avg < 0.5:
            return (
                "System reminder: Emphasize specificity and align proposals with the prospect's business outcomes."
            )
        if avg > 0.75:
            return (
                "System reminder: Continue the concise, action-oriented style that users responded positively to."
            )
        return ""

    async def insights(self, org_id: Optional[str]) -> Dict[str, Any]:
        async with get_session() as session:
            stmt = select(Feedback).order_by(Feedback.timestamp.desc()).limit(500)
            if org_id:
                stmt = stmt.where(Feedback.org_id == org_id)
            entries = (await session.exec(stmt)).all()

        agent_issue_map: Dict[str, Counter[str]] = defaultdict(Counter)
        agent_keywords: Dict[str, Counter[str]] = defaultdict(Counter)

        for entry in entries:
            agent = self._infer_agent(entry)
            issue = entry.type or "general"
            agent_issue_map[agent][issue] += 1
            if entry.comment:
                tokens = RewardModel._tokenize(entry.comment)
                agent_keywords[agent].update(tokens)

        agents_summary: List[Dict[str, Any]] = []
        for agent, issues in agent_issue_map.items():
            keywords = agent_keywords.get(agent, Counter())
            agents_summary.append(
                {
                    "agent": agent,
                    "total": int(sum(issues.values())),
                    "issues": [{"type": issue, "count": int(count)} for issue, count in issues.most_common(5)],
                    "keywords": [word for word, _ in keywords.most_common(8)],
                }
            )
        agents_summary.sort(key=lambda item: item["total"], reverse=True)
        return {"agents": agents_summary}

    async def _maybe_schedule_finetune(self) -> Optional[str]:
        if self._last_fine_tune_job:
            return self._last_fine_tune_job
        if OpenAI is None:
            return None
        target_model = os.getenv("OPENAI_FINE_TUNE_MODEL")
        if not target_model:
            return None
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return None
        min_samples = int(os.getenv("FINE_TUNE_MIN_SAMPLES", "20"))
        if self._trained_sample_count < min_samples:
            return None
        if not self.training_path.exists():
            return None
        try:
            client = OpenAI(api_key=api_key)
            with self.training_path.open("rb") as handle:
                upload = client.files.create(file=handle, purpose="fine-tune")
            job = client.fine_tuning.jobs.create(training_file=upload.id, model=target_model)
            self._last_fine_tune_job = job.id
            self._logger.info(
                "fine_tune_scheduled",
                extra={"feedback": {"job_id": job.id, "model": target_model}},
            )
            return job.id
        except Exception as exc:  # pragma: no cover - optional path
            monitoring.capture_exception(exc)
            self._logger.warning("Failed to schedule fine-tune: %s", exc)
            return None

    async def _collect_samples(self, org_id: Optional[str]) -> List[Sample]:
        proposals_by_lead: Dict[int, Proposal] = {}
        async with get_session() as session:
            stmt = select(Feedback).order_by(Feedback.timestamp.asc())
            if org_id:
                stmt = stmt.where(Feedback.org_id == org_id)
            entries = (await session.exec(stmt)).all()

            if not entries:
                return []

            lead_ids = {entry.lead_id for entry in entries if entry.lead_id}
            leads: Dict[int, Lead] = {}
            if lead_ids:
                lead_id_list = [lead_id for lead_id in lead_ids if lead_id is not None]
                if lead_id_list:
                    lead_rows = (
                        await session.exec(select(Lead).where(Lead.id.in_(lead_id_list)))
                    ).all()
                else:
                    lead_rows = []
                leads = {lead.id: lead for lead in lead_rows if lead and lead.id is not None}

            if lead_ids:
                lead_id_list = [lead_id for lead_id in lead_ids if lead_id is not None]
                if lead_id_list:
                    proposal_rows = (
                        await session.exec(
                            select(Proposal)
                            .where(Proposal.lead_id.in_(lead_id_list))
                            .order_by(Proposal.lead_id.asc(), Proposal.created_at.desc())
                        )
                    ).all()
                else:
                    proposal_rows = []
                for proposal in proposal_rows:
                    if proposal.lead_id not in proposals_by_lead:
                        proposals_by_lead[proposal.lead_id] = proposal

        samples: List[Sample] = []
        for entry in entries:
            lead = leads.get(entry.lead_id) if entry.lead_id else None
            prompt_text = lead.message if lead else (entry.comment or "")
            input_text = entry.comment or ""
            output_text = entry.edited_text or ""
            if not output_text and entry.lead_id:
                proposal = proposals_by_lead.get(entry.lead_id)
                if proposal and proposal.content:
                    output_text = proposal.content

            label = self._infer_label(entry)
            agent = self._infer_agent(entry)
            metadata = {
                "user_id": entry.user_id,
                "org_id": entry.org_id,
                "lead_id": entry.lead_id,
                "type": entry.type,
                "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
                "agent": agent,
            }
            samples.append(
                Sample(
                    prompt=prompt_text or "",
                    input_text=input_text or "",
                    output_text=output_text or "",
                    label=label,
                    agent=agent,
                    metadata=metadata,
                )
            )
        return samples

    @staticmethod
    def _infer_label(entry: Feedback) -> int:
        text = (entry.type or "").lower()
        comment = (entry.comment or "").lower()
        for hint in POSITIVE_HINTS:
            if hint in text or hint in comment:
                return 1
        for hint in NEGATIVE_HINTS:
            if hint in text or hint in comment:
                return 0
        # Default to negative to bias towards caution
        return 0

    @staticmethod
    def _infer_agent(entry: Feedback) -> str:
        comment = entry.comment or ""
        match = AGENT_PATTERN.search(comment)
        if match:
            return match.group(1).lower()
        if entry.type and ":" in entry.type:
            return entry.type.split(":", 1)[0].lower()
        if entry.type and "_" in entry.type:
            return entry.type.split("_", 1)[0].lower()
        return "default"

    def _update_agent_stats(self, agent: str, score: float) -> None:
        stats = self._agent_stats[agent]
        count = stats["count"]
        new_count = count + 1.0
        stats["avg"] = (stats["avg"] * count + score) / new_count
        stats["count"] = new_count
        stats["last"] = score

    def _export_path_for_org(self, org_id: Optional[str]) -> Path:
        if not org_id:
            return self.training_path
        safe = re.sub(r"[^A-Za-z0-9_\-]", "_", org_id)
        return self.training_path.parent / f"training_{safe}.jsonl"


feedback_loop = FeedbackLoop()
try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None  # type: ignore[assignment]
