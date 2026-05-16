"""
Data models for the orchestration system.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class StepStatus(Enum):
    """Status of a single task step."""
    PENDING = "pending"
    WAITING = "waiting"  # Waiting for dependencies
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    PAUSED = "paused"
    PAUSED_BY_ERROR = "paused_by_error"


class PlanStatus(Enum):
    """Status of an orchestration plan."""
    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELED = "canceled"


@dataclass
class TaskStep:
    """A single executable step within an orchestration plan."""
    step_id: str
    agent_name: str  # "coder", "reviewer", "skill:web-search", etc.
    instruction: str
    status: StepStatus = StepStatus.PENDING
    depends_on: list[str] = field(default_factory=list)
    context_key: str = ""  # Output stored under this key in shared_context
    checkpoint_enabled: bool = True
    retry_count: int = 0
    max_retries: int = 2
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        if not self.context_key:
            self.context_key = f"step_result_{self.step_id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "agent_name": self.agent_name,
            "instruction": self.instruction,
            "status": self.status.value,
            "depends_on": self.depends_on,
            "context_key": self.context_key,
            "checkpoint_enabled": self.checkpoint_enabled,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "result": self.result,
            "error": self.error,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskStep:
        return cls(
            step_id=data["step_id"],
            agent_name=data["agent_name"],
            instruction=data["instruction"],
            status=StepStatus(data.get("status", "pending")),
            depends_on=data.get("depends_on", []),
            context_key=data.get("context_key", ""),
            checkpoint_enabled=data.get("checkpoint_enabled", True),
            retry_count=data.get("retry_count", 0),
            max_retries=data.get("max_retries", 2),
            result=data.get("result"),
            error=data.get("error"),
            started_at=datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None,
            finished_at=datetime.fromisoformat(data["finished_at"]) if data.get("finished_at") else None,
        )


@dataclass
class Checkpoint:
    """Persisted checkpoint for a step."""
    plan_id: str
    step_id: str
    step_context: dict[str, Any]  # shared_context snapshot
    plan_status: dict[str, str]  # step_id → StepStatus.value
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "step_id": self.step_id,
            "step_context": self.step_context,
            "plan_status": self.plan_status,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Checkpoint:
        return cls(
            plan_id=data["plan_id"],
            step_id=data["step_id"],
            step_context=data["step_context"],
            plan_status=data["plan_status"],
            created_at=datetime.fromisoformat(data["created_at"]),
        )


@dataclass
class OrchestrationPlan:
    """A complete orchestration plan containing a DAG of steps."""
    plan_id: str
    title: str
    steps: list[TaskStep] = field(default_factory=list)
    status: PlanStatus = PlanStatus.DRAFT
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: Optional[datetime] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(cls, title: str, steps: Optional[list[TaskStep]] = None) -> OrchestrationPlan:
        plan_id = f"plan_{uuid.uuid4().hex[:12]}"
        return cls(plan_id=plan_id, title=title, steps=steps or [])

    def get_step(self, step_id: str) -> Optional[TaskStep]:
        for step in self.steps:
            if step.step_id == step_id:
                return step
        return None

    def get_steps_by_status(self, status: StepStatus) -> list[TaskStep]:
        return [s for s in self.steps if s.status == status]

    def get_runnable_steps(self) -> list[TaskStep]:
        """Steps whose dependencies are all satisfied (SUCCESS) and are currently PENDING or WAITING."""
        runnable = []
        for step in self.steps:
            if step.status not in (StepStatus.PENDING, StepStatus.WAITING):
                continue
            deps_done = all(
                self.get_step(dep_id) and self.get_step(dep_id).status == StepStatus.SUCCESS
                for dep_id in step.depends_on
            )
            if deps_done:
                runnable.append(step)
        return runnable

    def is_complete(self) -> bool:
        return all(s.status == StepStatus.SUCCESS for s in self.steps)

    def is_failed(self) -> bool:
        return any(
            s.status in (StepStatus.FAILED, StepStatus.PAUSED_BY_ERROR) and s.retry_count >= s.max_retries
            for s in self.steps
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "title": self.title,
            "steps": [s.to_dict() for s in self.steps],
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "metadata": self.metadata,
        }

    def get_status_summary(self) -> dict[str, int]:
        counts: dict[str, int] = {s.value: 0 for s in StepStatus}
        for s in self.steps:
            counts[s.status.value] = counts.get(s.status.value, 0) + 1
        return counts


@dataclass
class StepResult:
    """Result of executing a single step."""
    step_id: str
    success: bool
    output: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    duration_ms: int = 0


@dataclass
class OrchestrationResult:
    """Result of a complete plan execution."""
    plan_id: str
    success: bool
    final_status: PlanStatus
    step_results: list[StepResult] = field(default_factory=list)
    shared_context: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    total_duration_ms: int = 0
