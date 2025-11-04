import asyncio
import copy
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Deque, Dict, List, Optional, Tuple

from backend import monitoring
from backend.agents.followups import compose as compose_followup
from backend.agents.lead_scoring import score as score_lead
from backend.agents.proposal_gen import draft as draft_proposal


logger = logging.getLogger("dag")
DAG_RUN_HISTORY: Deque[Dict[str, Any]] = deque(maxlen=50)


async def _run_in_thread(func, *args, **kwargs):
    return await asyncio.to_thread(func, *args, **kwargs)


async def lead_scorer_executor(inputs: Dict[str, Any], context: Dict[str, Any]) -> Tuple[Dict[str, Any], float]:
    lead = inputs["lead"]
    score = await _run_in_thread(score_lead, lead["name"], lead["email"], lead["message"])
    return {"score": score}, 0.002


async def proposal_executor(inputs: Dict[str, Any], context: Dict[str, Any]) -> Tuple[Dict[str, Any], float]:
    lead = inputs["lead"]
    text = await _run_in_thread(draft_proposal, lead["name"], lead["message"])
    return {"proposal": text}, 0.003


async def followup_executor(inputs: Dict[str, Any], context: Dict[str, Any]) -> Tuple[Dict[str, Any], float]:
    lead = inputs["lead"]
    message = await _run_in_thread(compose_followup, lead["name"], 3, lead.get("message", ""))
    return {"followup": message}, 0.001


AGENT_REGISTRY: Dict[str, Awaitable] = {
    "lead_scorer": lead_scorer_executor,
    "proposal_gen": proposal_executor,
    "followup_agent": followup_executor,
}


@dataclass
class AgentTask:
    id: str
    agent: str
    name: str
    inputs: Dict[str, Any] = field(default_factory=dict)
    depends_on: List[str] = field(default_factory=list)


@dataclass
class NodeResult:
    id: str
    name: str
    status: str
    cost: float
    duration_ms: float
    error: Optional[str] = None


EXAMPLE_DAG: Dict[str, Any] = {
    "context": {
        "lead": {
            "name": "Acme Founder",
            "email": "founder@acme.io",
            "message": "We need an MVP in four weeks with a $10k budget.",
            "client_type": "startup",
        }
    },
    "tasks": [
        {
            "id": "score",
            "name": "LeadScorer",
            "agent": "lead_scorer",
            "inputs": {"lead": "$lead"},
        },
        {
            "id": "proposal",
            "name": "ProposalGen",
            "agent": "proposal_gen",
            "depends_on": ["score"],
            "inputs": {"lead": "$lead", "score": "$score.score"},
        },
        {
            "id": "followup",
            "name": "FollowupAgent",
            "agent": "followup_agent",
            "depends_on": ["proposal"],
            "inputs": {"lead": "$lead"},
        },
    ],
}


class DAGRuntime:
    def __init__(self, spec: Dict[str, Any], registry: Optional[Dict[str, Any]] = None):
        self.spec = copy.deepcopy(spec)
        self.registry = registry or AGENT_REGISTRY
        self.logger = logger

    def _build_tasks(self) -> Dict[str, AgentTask]:
        tasks = {}
        for node in self.spec.get("tasks", []):
            task = AgentTask(
                id=node["id"],
                agent=node["agent"],
                name=node.get("name", node["agent"]),
                inputs=node.get("inputs", {}),
                depends_on=node.get("depends_on", []),
            )
            tasks[task.id] = task
        return tasks

    def _resolve(self, value: Any, context: Dict[str, Any]) -> Any:
        if isinstance(value, str) and value.startswith("$"):
            path = value[1:].split(".")
            ref: Any = context
            for part in path:
                if isinstance(ref, dict) and part in ref:
                    ref = ref[part]
                else:
                    raise KeyError(f"Unable to resolve reference '{value}'")
            return ref
        if isinstance(value, dict):
            return {k: self._resolve(v, context) for k, v in value.items()}
        if isinstance(value, list):
            return [self._resolve(v, context) for v in value]
        return value

    async def _execute_task(
        self,
        task: AgentTask,
        context: Dict[str, Any],
    ) -> Tuple[str, str, Optional[str], float, float]:
        executor = self.registry.get(task.agent)
        if not executor:
            raise ValueError(f"Unknown agent '{task.agent}' for task '{task.id}'")

        inputs = self._resolve(task.inputs, context)
        started = time.perf_counter()
        cost = 0.0
        status = "succeeded"
        error = None
        try:
            output, cost = await executor(inputs, context)
            context[task.id] = output
        except Exception as exc:  # pragma: no cover - defensive
            status = "failed"
            error = str(exc)
            monitoring.capture_exception(exc)
        duration_ms = (time.perf_counter() - started) * 1000
        await monitoring.record_run(
            stage=task.agent,
            user_id=context.get("user_id", "anonymous"),
            org_id=context.get("org_id"),
            lead_id=context.get("lead", {}).get("id"),
            success=status == "succeeded",
            duration_ms=duration_ms,
            error_text=error,
        )
        return task.id, status, error, cost, duration_ms

    async def run(self) -> Dict[str, Any]:
        tasks = self._build_tasks()
        if not tasks:
            raise ValueError("No tasks defined in DAG spec")

        context = self.spec.get("context", {})
        context = copy.deepcopy(context)

        in_degree = {task_id: len(task.depends_on) for task_id, task in tasks.items()}
        dependents: Dict[str, List[str]] = {task_id: [] for task_id in tasks.keys()}
        for task in tasks.values():
            for dep in task.depends_on:
                dependents.setdefault(dep, []).append(task.id)

        ready = [task_id for task_id, degree in in_degree.items() if degree == 0]
        running: Dict[str, asyncio.Task] = {}
        node_results: Dict[str, NodeResult] = {}
        total_cost = 0.0
        overall_status = "succeeded"

        async def schedule(task_id: str) -> None:
            task = tasks[task_id]
            running[task_id] = asyncio.create_task(self._execute_task(task, context))

        for task_id in ready:
            await schedule(task_id)

        while running:
            done, _ = await asyncio.wait(running.values(), return_when=asyncio.FIRST_COMPLETED)
            for completed in done:
                task_id, status, error, cost, duration = completed.result()
                total_cost += cost
                node_results[task_id] = NodeResult(
                    id=task_id,
                    name=tasks[task_id].name,
                    status=status,
                    cost=round(cost, 4),
                    duration_ms=round(duration, 2),
                    error=error,
                )
                del running[task_id]
                if status != "succeeded":
                    overall_status = "failed"
                    running.clear()
                    break
                for dep_id in dependents.get(task_id, []):
                    in_degree[dep_id] -= 1
                    if in_degree[dep_id] == 0 and dep_id not in running:
                        await schedule(dep_id)

        nodes = [node_results[task_id].__dict__ for task_id in tasks.keys() if task_id in node_results]
        result = {
            "nodes": nodes,
            "total_cost": round(total_cost, 4),
            "status": overall_status,
            "context": context,
            "timestamp": datetime.utcnow().isoformat(),
        }
        DAG_RUN_HISTORY.appendleft(result)
        return result


def default_spec() -> Dict[str, Any]:
    return json.loads(json.dumps(EXAMPLE_DAG))
