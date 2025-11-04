import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

import yaml
from sqlmodel import select

from backend.db import AgentKPI, get_session

logger = logging.getLogger("agent.registry")


@dataclass
class AgentConfig:
    name: str
    role: str
    goal: str
    tools: List[str]
    prompt_template: str
    metrics: Dict[str, Any]
    path: Path


class BaseAgent:
    def __init__(self, config: AgentConfig):
        self.config = config

    async def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:  # pragma: no cover - override
        raise NotImplementedError


class ScoutAgent(BaseAgent):
    async def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        lead = payload.get("lead", {})
        summary = lead.get("message", "").split(".")[0]
        return {
            "type": "scout_summary",
            "lead_name": lead.get("name"),
            "insights": summary,
            "confidence": 0.7,
        }


class CloserAgent(BaseAgent):
    async def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        proposal = payload.get("proposal", "")
        return {
            "type": "closing_strategy",
            "next_step": "Schedule call",
            "talking_points": [proposal[:120], "Highlight ROI"],
        }


class StrategistAgent(BaseAgent):
    async def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        lead = payload.get("lead", {})
        return {
            "type": "strategic_plan",
            "segments": [lead.get("client_type", "general")],
            "milestones": ["Discovery", "MVP", "Launch"],
        }


AGENT_CLASS_MAP: Dict[str, Type[BaseAgent]] = {
    "ScoutAgent": ScoutAgent,
    "CloserAgent": CloserAgent,
    "StrategistAgent": StrategistAgent,
}


def _load_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


class AgentRegistry:
    def __init__(self, config_dir: Optional[Path] = None):
        self.config_dir = config_dir or Path(os.getenv("AGENT_CONFIG_DIR", "agents/configs"))
        self.agents: Dict[str, BaseAgent] = {}
        self.configs: Dict[str, AgentConfig] = {}
        self.paths: Dict[str, Path] = {}

    def load(self) -> None:
        self.agents.clear()
        self.configs.clear()
        self.paths.clear()
        if not self.config_dir.exists():
            logger.warning("Agent config directory %s does not exist", self.config_dir)
            return
        for file in sorted(self.config_dir.glob("*.yaml")):
            data = _load_yaml(file)
            try:
                config = AgentConfig(
                    name=data["name"],
                    role=data.get("role", "agent"),
                    goal=data.get("goal", ""),
                    tools=data.get("tools", []),
                    prompt_template=data.get("prompt_template", ""),
                    metrics=data.get("metrics", {}),
                    path=file,
                )
            except KeyError as exc:
                logger.error("Invalid agent config %s: missing %s", file, exc)
                continue
            class_name = data.get("class", data.get("agent_class", "ScoutAgent"))
            agent_cls = AGENT_CLASS_MAP.get(class_name)
            if not agent_cls:
                logger.error("Unknown agent class '%s' in %s", class_name, file)
                continue
            agent = agent_cls(config)
            self.configs[config.name] = config
            self.agents[config.name] = agent
            self.paths[config.name] = file
            logger.info("Loaded agent %s (%s)", config.name, class_name)

    def get(self, name: str) -> Optional[BaseAgent]:
        return self.agents.get(name)

    def get_config(self, name: str) -> Optional[Dict[str, Any]]:
        config = self.configs.get(name)
        if not config:
            return None
        return {
            "name": config.name,
            "role": config.role,
            "goal": config.goal,
            "tools": config.tools,
            "prompt_template": config.prompt_template,
            "metrics": config.metrics,
        }

    def update_prompt(self, name: str, prompt: str) -> None:
        path = self.paths.get(name)
        if not path:
            raise KeyError(f"Agent '{name}' not found")
        data = _load_yaml(path)
        data["prompt_template"] = prompt
        with path.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(data, fh, sort_keys=False)
        self.load()

    async def status(self, org_id: Optional[str] = None) -> List[Dict[str, Any]]:
        async with get_session() as session:
            query = select(AgentKPI).order_by(AgentKPI.agent_name.asc())
            if org_id:
                query = query.where(AgentKPI.org_id == org_id)
            rows = (await session.exec(query)).all()
        metrics_map = {row.agent_name: row for row in rows}
        status = []
        for name, agent in self.agents.items():
            metrics = metrics_map.get(name)
            if metrics and metrics.total_runs:
                success = metrics.successes / metrics.total_runs
                avg_tokens = metrics.total_tokens / metrics.total_runs
                avg_latency = metrics.avg_response_ms
            else:
                success = 0.0
                avg_tokens = 0.0
                avg_latency = 0.0
            status.append(
                {
                    "name": name,
                    "role": agent.config.role,
                    "goal": agent.config.goal,
                    "success_rate": round(success, 3),
                    "avg_tokens": round(avg_tokens, 2),
                    "avg_latency_ms": round(avg_latency, 2),
                    "metrics": json.loads(json.dumps(agent.config.metrics)),
                }
            )
        return status


registry = AgentRegistry()
