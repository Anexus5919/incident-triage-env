"""
Incident-triage rubrics for reward computation.

Provides ``IncidentTriageRubric`` that extends
``ExponentialDiscountingTrajectoryRubric`` to compute temporally-discounted
rewards based on the quality of the agent's triage trajectory.

Unlike chess (binary win/loss), incident triage has a continuous score built
from four components:

* Investigation quality  (0.00 -- 0.20)
* Diagnosis accuracy     (0.00 -- 0.30)
* Remediation success    (0.00 -- 0.40)
* Efficiency bonus       (0.00 -- 0.10)

Total maximum per episode: **1.0**
"""

from __future__ import annotations

from typing import Any, List, Tuple

try:
    from openenv.core.rubrics.trajectory import (
        ExponentialDiscountingTrajectoryRubric,
    )
except ModuleNotFoundError:
    # ----- compatibility fallback (mirrors chess_env) -----
    class ExponentialDiscountingTrajectoryRubric:  # type: ignore[no-redef]
        """Minimal fallback when ``openenv-core`` lacks the rubrics subpackage."""

        def __init__(
            self, gamma: float = 0.99, intermediate_reward: float = 0.0
        ) -> None:
            self.gamma = gamma
            self.intermediate_reward = intermediate_reward
            self._trajectory: List[Tuple[Any, Any]] = []

        def __call__(self, action: Any, observation: Any) -> float:
            self._trajectory.append((action, observation))
            if getattr(observation, "done", False):
                return self.score_trajectory(self._trajectory)
            return self.intermediate_reward

        def reset(self) -> None:
            self._trajectory = []

        def compute_step_rewards(self) -> List[float]:
            if not self._trajectory:
                return []
            final_score = self.score_trajectory(self._trajectory)
            total_steps = len(self._trajectory)
            return [
                self.gamma ** (total_steps - 1 - step_index) * final_score
                for step_index in range(total_steps)
            ]

        def score_trajectory(
            self, trajectory: List[Tuple[Any, Any]]
        ) -> float:  # pragma: no cover
            raise NotImplementedError


class IncidentTriageRubric(ExponentialDiscountingTrajectoryRubric):
    """Score an incident-triage episode via cumulative per-step rewards.

    The environment emits small, additive rewards at each step (investigation
    hits, correct diagnosis, correct remediation, efficiency bonus).  The rubric
    sums them at the end of the trajectory and clamps to [0.0, 1.0].

    Per-step discounted reward for training:
        ``r_t = gamma^(T-1-t) * final_cumulative_score``
    """

    def score_trajectory(
        self, trajectory: List[Tuple[Any, Any]]
    ) -> float:
        if not trajectory:
            return 0.001
        total = sum(
            float(getattr(obs, "reward", 0.0)) for _, obs in trajectory
        )
        return max(0.001, min(0.999, total))
