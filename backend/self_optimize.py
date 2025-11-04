"""Self-optimization scheduler that synthesizes metrics into actionable suggestions."""

import asyncio
import json
import os
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy import func, select

from backend import monitoring
from backend.db import AgentKPI, Feedback, Lead, get_session

try:  # optional dependency
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None  # type: ignore[assignment]


REPORT_DIR = Path("data/self_optimize/reports")
SUGGESTION_DIR = Path("data/self_optimize/suggestions")
PROMPT_DIR = Path("prompts")

REPORT_DIR.mkdir(parents=True, exist_ok=True)
SUGGESTION_DIR.mkdir(parents=True, exist_ok=True)
PROMPT_DIR.mkdir(parents=True, exist_ok=True)


class SelfOptimizer:
    """Coordinate data collection, suggestion drafting, and notification logic."""

    def __init__(self) -> None:
        self._openai_client: Optional["OpenAI"] = None

    async def run(self) -> Dict[str, Any]:
        """Execute the end-to-end self optimization workflow.

        Returns:
            Dict[str, Any]: Metadata about the generated report and prompts.
        """
        metrics = await self._collect_metrics()
        suggestions = self._derive_suggestions(metrics)
        summary = await self._summarize(metrics, suggestions)
        timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        report_path = self._write_report(timestamp, metrics, suggestions, summary)
        prompt_paths = self._write_prompt_drafts(timestamp, suggestions)
        pr_info = self._generate_pr_instructions(timestamp, prompt_paths)
        await self._notify(summary, pr_info)
        return {
            "timestamp": timestamp,
            "report_path": str(report_path),
            "prompt_suggestions": [str(path) for path in prompt_paths],
            "summary": summary,
            "suggestions": suggestions,
            "pr_instructions": pr_info,
        }

    async def _collect_metrics(self) -> Dict[str, Any]:
        """Aggregate agent KPIs, feedback records, and lead mix.

        Returns:
            Dict[str, Any]: Combined metrics for downstream analysis.
        """
        async with get_session() as session:
            kpis = (await session.exec(select(AgentKPI))).all()
            feedback_rows = (
                await session.exec(select(Feedback).order_by(Feedback.timestamp.desc()).limit(200))
            ).all()
            recent_leads = (
                await session.exec(select(Lead.client_type, func.count()).group_by(Lead.client_type))
            ).all()

        kpi_metrics: Dict[str, Dict[str, Any]] = {}
        for row in kpis:
            total_runs = row.total_runs or 1
            success_rate = (row.successes or 0) / total_runs
            avg_tokens = (row.total_tokens or 0) / total_runs
            kpi_metrics[row.agent_name] = {
                "success_rate": round(success_rate, 3),
                "avg_tokens": round(avg_tokens, 2),
                "avg_response_ms": round(row.avg_response_ms or 0, 2),
                "acceptance_rate": round(row.acceptance_rate or 0, 3),
                "roi": round(row.roi or 0, 3),
                "total_runs": total_runs,
            }

        feedback_types: Dict[str, int] = {}
        feedback_comments: Dict[str, List[str]] = {}
        for entry in feedback_rows:
            feedback_types[entry.type] = feedback_types.get(entry.type, 0) + 1
            feedback_comments.setdefault(entry.type, []).append(entry.comment or "")

        leads_breakdown = {client_type: count for client_type, count in recent_leads}
        return {
            "agent_kpis": kpi_metrics,
            "feedback_breakdown": feedback_types,
            "feedback_comments": feedback_comments,
            "leads_breakdown": leads_breakdown,
        }

    def _derive_suggestions(self, metrics: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """Translate raw metrics into actionable agent recommendations.

        Args:
            metrics: Collected KPI and feedback data.

        Returns:
            Dict[str, Dict[str, Any]]: Per-agent suggestion payloads.
        """
        suggestions: Dict[str, Dict[str, Any]] = {}
        kpis = metrics.get("agent_kpis", {})
        for agent, data in kpis.items():
            success_rate = data.get("success_rate", 0.0)
            acceptance = data.get("acceptance_rate", 0.0)
            avg_tokens = data.get("avg_tokens", 0.0)
            adjustments: List[str] = []
            if success_rate < 0.8:
                adjustments.append("Review guardrails and clarify decision criteria; success < 80%.")
            if acceptance < 0.5:
                adjustments.append("Tune tone to emphasize outcomes and social proof (acceptance < 50%).")
            if avg_tokens > 700:
                adjustments.append("Consider truncating memory context to reduce token usage.")
            if not adjustments:
                adjustments.append("Maintain current prompt; metrics within target ranges.")
            suggestions[agent] = {
                "status": "attention" if success_rate < 0.8 or acceptance < 0.5 else "healthy",
                "recommendations": adjustments,
                "thresholds": {
                    "success_rate": success_rate,
                    "acceptance_rate": acceptance,
                    "avg_tokens": avg_tokens,
                },
            }
        return suggestions

    async def _summarize(
        self, metrics: Dict[str, Any], suggestions: Dict[str, Dict[str, Any]]
    ) -> str:
        """Call OpenAI (or fallback) to produce a concise optimization summary.

        Args:
            metrics: Aggregated KPI data.
            suggestions: Recommendation payload.

        Returns:
            str: Narrative summary of optimization tasks.
        """
        client = self._get_openai_client()
        context = textwrap.dedent(
            f"""
            Metrics Snapshot:
            Agent KPIs: {json.dumps(metrics.get("agent_kpis", {}), indent=2)}
            Feedback Breakdown: {json.dumps(metrics.get("feedback_breakdown", {}), indent=2)}
            Leads By Type: {json.dumps(metrics.get("leads_breakdown", {}), indent=2)}
            Suggestions: {json.dumps(suggestions, indent=2)}
            """
        )
        if not client:
            return self._fallback_summary(metrics, suggestions)
        prompt = (
            "You are the FreeAgent self-optimization module. Review the metrics and craft a concise report with:\n"
            "1. Top 3 optimization recommendations.\n"
            "2. Example prompt or threshold adjustment per affected agent.\n"
            "3. Notable failure patterns observed.\n"
            "Keep it under 250 words.\n\n"
            f"{context}"
        )
        try:
            response = client.responses.create(model=os.getenv("SELF_OPTIMIZE_MODEL", "gpt-4o-mini"), input=prompt)
            return response.output_text.strip()
        except Exception as exc:  # pragma: no cover
            monitoring.capture_exception(exc)
            return self._fallback_summary(metrics, suggestions)

    @staticmethod
    def _fallback_summary(
        metrics: Dict[str, Any],
        suggestions: Dict[str, Dict[str, Any]],
    ) -> str:
        """Generate a summary when LLM access fails.

        Args:
            metrics: KPI dataset.
            suggestions: Recommendation payload.

        Returns:
            str: Plain-text summary.
        """
        lines = ["Self-Optimization Summary (fallback):"]
        attention_agents = [name for name, data in suggestions.items() if data["status"] == "attention"]
        lines.append(f"- Agents needing attention: {', '.join(attention_agents) if attention_agents else 'None'}")
        top_feedback = sorted(metrics.get("feedback_breakdown", {}).items(), key=lambda item: item[1], reverse=True)[:3]
        if top_feedback:
            lines.append("- Frequent feedback themes:")
            for theme, count in top_feedback:
                lines.append(f"  • {theme}: {count}")
        lines.append("- Recommendations:")
        for agent, data in suggestions.items():
            rec = data["recommendations"][0]
            lines.append(f"  • {agent}: {rec}")
        return "\n".join(lines)

    def _write_report(
        self,
        timestamp: str,
        metrics: Dict[str, Any],
        suggestions: Dict[str, Dict[str, Any]],
        summary: str,
    ) -> Path:
        """Persist a markdown report capturing metrics, summary, and recommendations.

        Args:
            timestamp: Report timestamp label.
            metrics: Aggregated KPI data.
            suggestions: Recommendation payload.
            summary: Narrative summary.

        Returns:
            Path: Location of the generated report.
        """
        report_path = REPORT_DIR / f"{timestamp}.md"
        content = [
            f"# Self Optimization Report — {timestamp}",
            "",
            "## Executive Summary",
            summary,
            "",
            "## Agent KPI Snapshot",
            "```json",
            json.dumps(metrics.get("agent_kpis", {}), indent=2),
            "```",
            "",
            "## Feedback Breakdown",
            "```json",
            json.dumps(metrics.get("feedback_breakdown", {}), indent=2),
            "```",
            "",
            "## Recommendations",
        ]
        for agent, data in suggestions.items():
            content.append(f"### {agent}")
            for rec in data["recommendations"]:
                content.append(f"- {rec}")
            thresholds = data.get("thresholds", {})
            content.append(f"  - Metrics: {json.dumps(thresholds)}")
            content.append("")
        report_path.write_text("\n".join(content), encoding="utf-8")
        return report_path

    def _write_prompt_drafts(self, timestamp: str, suggestions: Dict[str, Dict[str, Any]]) -> List[Path]:
        """Create markdown prompt drafts for each agent recommendation.

        Args:
            timestamp: Execution timestamp.
            suggestions: Recommendation payload.

        Returns:
            List[Path]: Paths to generated suggestion files.
        """
        bundle_dir = SUGGESTION_DIR / timestamp
        bundle_dir.mkdir(parents=True, exist_ok=True)
        paths: List[Path] = []
        for agent, data in suggestions.items():
            lines = [
                f"# Suggested prompt adjustments for {agent}",
                "",
                "## Recommendations",
            ]
            lines.extend(f"- {rec}" for rec in data["recommendations"])
            lines.append("")
            lines.append("## Proposed Prompt Stub")
            lines.append(
                textwrap.dedent(
                    f"""
                    You are the {agent.replace('_', ' ')} agent for FreeAgent. Emphasize:
                    1. Outcome-driven language aligned with the client's stated goals.
                    2. Personalization cues drawn from lead history.
                    3. Clear next actions and success metrics.
                    """
                ).strip()
            )
            path = bundle_dir / f"{agent}.md"
            path.write_text("\n".join(lines), encoding="utf-8")
            prompt_target = PROMPT_DIR / f"{agent}.txt"
            if not prompt_target.exists():
                prompt_target.write_text(lines[-1] + "\n", encoding="utf-8")
            paths.append(path)
        return paths

    def _generate_pr_instructions(self, timestamp: str, prompt_paths: List[Path]) -> Dict[str, Any]:
        """Return instructions for creating a suggestions branch and PR.

        Args:
            timestamp: Execution timestamp.
            prompt_paths: Generated prompt draft paths.

        Returns:
            Dict[str, Any]: Branch name and workflow guidance.
        """
        branch_name = f"suggestions/{timestamp}"
        instructions = textwrap.dedent(
            f"""
            Suggested workflow:
            1. git checkout -b {branch_name}
            2. Review generated prompt drafts under {SUGGESTION_DIR / timestamp}
            3. Apply changes to {PROMPT_DIR} as needed
            4. git commit -am "self_optimize: weekly agent tuning suggestions"
            5. git push origin {branch_name}
            6. Open PR targeting suggestions branch, attach report {REPORT_DIR / f"{timestamp}.md"}
            """
        ).strip()
        return {
            "branch": branch_name,
            "instructions": instructions,
            "files": [str(path) for path in prompt_paths],
        }

    async def _notify(self, summary: str, pr_info: Dict[str, Any]) -> None:
        """Send a Slack notification summarizing the optimization results.

        Args:
            summary: Optimization summary to broadcast.
            pr_info: Git workflow instructions.
        """
        webhook = os.getenv("SLACK_WEBHOOK_URL")
        if not webhook:
            return
        payload = {
            "text": "*Self Optimization Report Ready*\n"
            f"{summary[:400]}...\n"
            f"Suggested branch: `{pr_info.get('branch')}`",
        }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(webhook, json=payload)
        except Exception as exc:  # pragma: no cover
            monitoring.capture_exception(exc)

    def _get_openai_client(self):
        """Return an OpenAI client if credentials are available.

        Returns:
            OpenAI | None: Configured OpenAI client or None.
        """
        if self._openai_client is not None:
            return self._openai_client
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key and OpenAI is not None:
            try:
                self._openai_client = OpenAI(api_key=api_key)
            except Exception as exc:  # pragma: no cover
                monitoring.capture_exception(exc)
                self._openai_client = None
        return self._openai_client


optimizer = SelfOptimizer()
