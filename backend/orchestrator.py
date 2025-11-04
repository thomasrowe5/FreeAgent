import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from sqlmodel import select

from backend.agents.followups import compose as compose_followup
from backend.agents.lead_scoring import score as score_lead
from backend.agents.proposal_gen import draft as draft_proposal
from backend.analytics import recompute_snapshot_for_user
from backend.db import GmailToken, Lead, Proposal, Run, get_session
from backend.integrations.gmail import send_email as gmail_send_email
from backend import billing, monitoring


@dataclass
class WorkflowResult:
    lead_id: int
    score: Optional[float] = None
    proposal_id: Optional[int] = None
    email_sent: bool = False
    followup_status: Optional[str] = None


class Workflow:
    """Coordinates the lead → proposal → follow-up sequence with retries."""

    steps = ("score", "proposal", "send", "followup")
    stage_map = {
        "score": "lead_scoring",
        "proposal": "proposal_generation",
        "send": "proposal_email",
        "followup": "followup",
    }
    usage_actions = {
        "proposal": "proposal",
        "followup": "followup",
    }

    def __init__(self, lead_id: int, user_id: str, *, max_attempts: int = 3, logger: Optional[logging.Logger] = None):
        self.lead_id = lead_id
        self.user_id = user_id
        self.max_attempts = max_attempts
        self.logger = logger or logging.getLogger("workflow")
        self._usage_recorded: set[str] = set()

    async def run(self, start_from: str = "score") -> WorkflowResult:
        result = WorkflowResult(lead_id=self.lead_id)
        start_index = self._get_step_index(start_from)

        try:
            if start_index <= self._get_step_index("score"):
                result.score = await self._run_with_retry("score", self._score_lead)

            if start_index <= self._get_step_index("proposal"):
                proposal = await self._run_with_retry("proposal", self._generate_proposal)
                if proposal:
                    result.proposal_id = proposal.id

            if start_index <= self._get_step_index("send"):
                sent = await self._run_with_retry("send", self._send_proposal_email, allow_skip=True)
                result.email_sent = bool(sent)

            if start_index <= self._get_step_index("followup"):
                status = await self._run_with_retry("followup", self._schedule_followup)
                result.followup_status = status
        finally:
            await recompute_snapshot_for_user(self.user_id)

        return result

    def enqueue(self, start_from: str = "score") -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError as exc:  # pragma: no cover - requires async context
            self.logger.error(
                "workflow",
                extra={
                    "workflow": {
                        "lead_id": self.lead_id,
                        "user_id": self.user_id,
                        "step": "enqueue",
                        "status": "failed",
                        "error": str(exc),
                    }
                },
            )
            raise
        loop.create_task(self.run(start_from=start_from))

    async def _run_with_retry(self, step: str, func, allow_skip: bool = False):
        last_exc: Optional[Exception] = None
        for attempt in range(1, self.max_attempts + 1):
            stage_name = self.stage_map.get(step)
            usage_action = self.usage_actions.get(step)
            started = time.perf_counter()
            try:
                if usage_action and attempt == 1 and usage_action not in self._usage_recorded:
                    await billing.increment_usage(self.user_id, usage_action)
                    self._usage_recorded.add(usage_action)

                self._log(step, "start", attempt)
                result = await func()
                duration_ms = (time.perf_counter() - started) * 1000
                if stage_name:
                    await monitoring.record_run(
                        stage=stage_name,
                        user_id=self.user_id,
                        lead_id=self.lead_id,
                        success=True,
                        duration_ms=duration_ms,
                    )
                self._log(step, "success", attempt, extra={"result": self._safe_repr(result)})
                return result
            except Exception as exc:  # pragma: no cover - defensive logging
                last_exc = exc
                self._log(step, "error", attempt, extra={"error": str(exc)})
                duration_ms = (time.perf_counter() - started) * 1000
                if stage_name:
                    await monitoring.record_run(
                        stage=stage_name,
                        user_id=self.user_id,
                        lead_id=self.lead_id,
                        success=False,
                        duration_ms=duration_ms,
                        error_text=f"Attempt {attempt}: {monitoring.format_exception(exc)}",
                    )
                if not isinstance(exc, billing.UsageLimitExceeded):
                    monitoring.capture_exception(exc)
                if isinstance(exc, billing.UsageLimitExceeded):
                    raise
                if attempt >= self.max_attempts:
                    if allow_skip:
                        self._log(step, "skipped", attempt, extra={"reason": str(exc)})
                        return None
                    raise
                await asyncio.sleep(min(2 ** attempt, 5))
        if allow_skip:
            return None
        raise last_exc  # type: ignore[misc]

    def _log(self, step: str, status: str, attempt: int, extra: Optional[Dict[str, Any]] = None) -> None:
        payload = {"lead_id": self.lead_id, "user_id": self.user_id, "step": step, "status": status, "attempt": attempt}
        if extra:
            payload.update(extra)
        self.logger.info("workflow", extra={"workflow": payload})

    def _get_step_index(self, step: str) -> int:
        try:
            return self.steps.index(step)
        except ValueError:
            raise ValueError(f"Unknown workflow step '{step}'")

    @staticmethod
    def _safe_repr(value: Any) -> Any:
        try:
            return repr(value)
        except Exception:  # pragma: no cover - fallback
            return str(value)

    async def _score_lead(self) -> float:
        async with get_session() as session:
            lead = await session.get(Lead, self.lead_id)
            if not lead:
                raise ValueError(f"Lead {self.lead_id} not found")
            score = score_lead(lead.name, lead.email, lead.message)
            lead.score = score
            session.add(lead)
            session.add(Run(kind="lead_scoring", lead_id=lead.id))
            await session.commit()
            return score

    async def _generate_proposal(self) -> Proposal:
        async with get_session() as session:
            lead = await session.get(Lead, self.lead_id)
            if not lead:
                raise ValueError(f"Lead {self.lead_id} not found")
            content = draft_proposal(lead.name, lead.message)
            proposal = Proposal(lead_id=lead.id, content=content)
            lead.status = "proposal_sent"
            session.add(proposal)
            session.add(lead)
            session.add(Run(kind="proposal", lead_id=lead.id))
            await session.commit()
            await session.refresh(proposal)
            return proposal

    async def _send_proposal_email(self) -> bool:
        async with get_session() as session:
            token = await session.get(GmailToken, self.user_id)
            if not token:
                raise RuntimeError("No Gmail credentials configured for user")

            proposal = (
                await session.exec(
                    select(Proposal)
                    .where(Proposal.lead_id == self.lead_id)
                    .order_by(Proposal.created_at.desc())
                    .limit(1)
                )
            ).first()
            lead = await session.get(Lead, self.lead_id)
            if not lead or not proposal:
                raise ValueError("Proposal not found for lead")
            subject = f"Proposal for {lead.name}"
            body = proposal.content
            recipient = lead.email

        await gmail_send_email(self.user_id, recipient, subject, body)
        return True

    async def _schedule_followup(self) -> str:
        async with get_session() as session:
            lead = await session.get(Lead, self.lead_id)
            if not lead:
                raise ValueError(f"Lead {self.lead_id} not found")
            followup_text = compose_followup(lead.name, 3, lead.message)
            lead.status = "followup_pending"
            session.add(lead)
            session.add(Run(kind="followup", lead_id=lead.id))
            await session.commit()
            return lead.status
