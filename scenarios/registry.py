"""
Task registry for incident-triage scenarios.

Each scenario is a self-contained incident definition that the environment
loads on ``reset()``.  Scenarios are registered at import time by the
individual scenario modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Set


@dataclass
class ServiceInfo:
    """Static data for a single simulated service."""

    name: str
    status: str  # "healthy", "degraded", "down"
    logs: str = ""
    metrics: Dict[str, Any] = field(default_factory=dict)
    dependencies: List[str] = field(default_factory=list)


@dataclass
class Scenario:
    """A complete incident scenario / task definition."""

    # Identity
    task_id: str
    difficulty: str  # "easy", "medium", "hard"
    title: str
    description: str

    # System topology
    services: Dict[str, ServiceInfo] = field(default_factory=dict)

    # Initial observations
    initial_alerts: List[dict] = field(default_factory=list)

    # Investigation data (what the agent sees on check_* commands)
    log_data: Dict[str, str] = field(default_factory=dict)
    metrics_data: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    dependency_data: Dict[str, str] = field(default_factory=dict)

    # Correct answers
    root_cause: str = ""
    root_cause_service: str = ""
    root_cause_keywords: List[str] = field(default_factory=list)  # fuzzy match
    correct_remediations: List[str] = field(default_factory=list)
    alternative_remediations: Dict[str, float] = field(default_factory=dict)

    # Scoring budgets (MUST sum to 1.0)
    reward_investigation: float = 0.20
    reward_diagnosis: float = 0.30
    reward_remediation: float = 0.40
    reward_efficiency: float = 0.10

    # Episode limits
    max_steps: int = 15
    optimal_steps: int = 4

    # Red herrings (medium/hard only)
    red_herring_services: Set[str] = field(default_factory=set)

    # ---- helpers ----

    @property
    def max_total_reward(self) -> float:
        """Total possible reward -- always 1.0 by design."""
        return 1.0

    @property
    def service_names(self) -> List[str]:
        return list(self.services.keys())

    def relevant_services(self) -> List[str]:
        """Services on the actual causal chain (not red herrings)."""
        return [s for s in self.services if s not in self.red_herring_services]


# ---- global registry ----

TASK_REGISTRY: Dict[str, Scenario] = {}


def register_task(scenario: Scenario) -> None:
    """Add a scenario to the global registry."""
    TASK_REGISTRY[scenario.task_id] = scenario


def get_task(task_id: str) -> Scenario:
    """Look up a scenario by id; raises ``ValueError`` if missing."""
    if task_id not in TASK_REGISTRY:
        raise ValueError(
            f"Unknown task_id: {task_id!r}. Available: {list(TASK_REGISTRY.keys())}"
        )
    return TASK_REGISTRY[task_id]


def list_tasks() -> List[str]:
    """Return all registered task ids."""
    return list(TASK_REGISTRY.keys())
