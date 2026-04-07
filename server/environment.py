"""
Incident Triage Environment — core game loop.

Implements the OpenEnv ``Environment`` interface (Gym-style):
    reset()  -> IncidentObservation
    step()   -> IncidentObservation
    state    -> IncidentState   (property)

Follows the same patterns as the chess_env reference implementation.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional, Set

from openenv.core.env_server import Environment

from ..models import (
    AlertInfo,
    IncidentAction,
    IncidentObservation,
    IncidentState,
    ServiceStatus,
)
from ..scenarios import list_tasks
from ..scenarios.registry import Scenario, get_task
from .rubrics import IncidentTriageRubric


class IncidentTriageEnvironment(Environment):
    """
    SRE Incident Triage environment.

    An AI agent receives production alerts and must:
    1. Investigate services (check_logs, check_metrics, check_dependencies)
    2. Diagnose the root cause
    3. Apply the correct remediation

    Three built-in tasks: easy, medium, hard.
    """

    VALID_COMMANDS: List[str] = [
        "check_logs",
        "check_metrics",
        "check_dependencies",
        "diagnose",
        "remediate",
        "escalate",
    ]

    def __init__(self, default_task_id: str = "easy_disk_full") -> None:
        super().__init__(rubric=IncidentTriageRubric(gamma=0.99))
        self._default_task_id = default_task_id
        self._scenario: Optional[Scenario] = None
        self._state: Optional[IncidentState] = None
        self._investigated: Set[str] = set()
        self._diagnosis_submitted: bool = False
        self._diagnosis_correct: bool = False
        self._remediations_applied: List[str] = []
        self._cumulative_reward: float = 0.0
        self.reset()

    # ------------------------------------------------------------------ #
    #  OpenEnv interface                                                   #
    # ------------------------------------------------------------------ #

    def reset(
        self,
        seed: Optional[int] = None,
        episode_id: Optional[str] = None,
        **kwargs: Any,
    ) -> IncidentObservation:
        """Start a new incident episode.

        Keyword Args:
            task_id: One of ``list_tasks()`` — selects the scenario.
        """
        self._reset_rubric()

        task_id = kwargs.get("task_id", self._default_task_id)
        self._scenario = get_task(task_id)

        self._state = IncidentState(
            episode_id=episode_id or str(uuid.uuid4()),
            step_count=0,
            task_id=task_id,
        )
        self._investigated = set()
        self._diagnosis_submitted = False
        self._diagnosis_correct = False
        self._remediations_applied = []
        self._cumulative_reward = 0.0

        return self._make_observation(
            command_output=(
                f"=== INCIDENT: {self._scenario.title} ===\n\n"
                f"{self._scenario.description}\n\n"
                f"Available commands: {', '.join(self.VALID_COMMANDS)}\n"
                f"Available services: {', '.join(self._scenario.service_names)}"
            ),
        )

    def step(
        self,
        action: IncidentAction,
        timeout_s: Optional[float] = None,
        **kwargs: Any,
    ) -> IncidentObservation:
        """Execute one triage action and return the resulting observation."""
        if self._scenario is None or self._state is None:
            raise RuntimeError("Environment not initialised. Call reset() first.")

        self._state.step_count += 1
        self._state.time_elapsed_minutes += 3  # each step ≈ 3 min simulated
        action_str = f"{action.command}:{action.target}"
        self._state.actions_taken.append(action_str)

        # ---- route to handler ----
        command = action.command.lower().strip()
        handler = {
            "check_logs": self._handle_check_logs,
            "check_metrics": self._handle_check_metrics,
            "check_dependencies": self._handle_check_dependencies,
            "diagnose": self._handle_diagnose,
            "remediate": self._handle_remediate,
            "escalate": self._handle_escalate,
        }.get(command)

        if handler is None:
            output = (
                f"Unknown command: '{command}'.\n"
                f"Valid commands: {', '.join(self.VALID_COMMANDS)}"
            )
            reward = 0.0
        else:
            output, reward = handler(action)

        self._cumulative_reward += reward

        # ---- check termination ----
        done = self._check_done()

        # ---- efficiency bonus (only at episode end when remediated) ----
        efficiency_bonus = 0.0
        if done and self._state.remediated:
            s = self._scenario
            ratio = max(
                0.0,
                1.0 - (self._state.step_count - s.optimal_steps) / s.max_steps,
            )
            efficiency_bonus = s.reward_efficiency * ratio
            self._cumulative_reward += efficiency_bonus

        step_reward = reward + efficiency_bonus

        obs = self._make_observation(
            command_output=output,
            reward=round(step_reward, 4),
            done=done,
        )

        self._apply_rubric(action, obs)
        return obs

    @property
    def state(self) -> IncidentState:
        """Return the current episode state."""
        if self._state is None:
            return IncidentState()
        return self._state

    # ------------------------------------------------------------------ #
    #  Command handlers — each returns (output_text, step_reward)          #
    # ------------------------------------------------------------------ #

    def _handle_check_logs(self, action: IncidentAction) -> tuple:
        target = action.target.strip()
        s = self._scenario
        assert s is not None

        if target not in s.services:
            return (
                f"Unknown service: '{target}'.\n"
                f"Available services: {', '.join(s.service_names)}",
                0.0,
            )

        key = f"logs:{target}"
        is_new = key not in self._investigated
        self._investigated.add(key)

        if target not in self._state.investigated_services:
            self._state.investigated_services.append(target)

        logs = s.log_data.get(target, f"(No log data available for {target})")
        output = f"=== Logs for {target} ===\n{logs}"

        reward = self._investigation_reward(target, is_new)
        return output, reward

    def _handle_check_metrics(self, action: IncidentAction) -> tuple:
        target = action.target.strip()
        s = self._scenario
        assert s is not None

        if target not in s.services:
            return (
                f"Unknown service: '{target}'.\n"
                f"Available services: {', '.join(s.service_names)}",
                0.0,
            )

        key = f"metrics:{target}"
        is_new = key not in self._investigated
        self._investigated.add(key)

        if target not in self._state.investigated_services:
            self._state.investigated_services.append(target)

        metrics = s.metrics_data.get(target, {})
        lines = [f"=== Metrics for {target} ==="]
        for k, v in metrics.items():
            lines.append(f"  {k}: {v}")

        reward = self._investigation_reward(target, is_new)
        return "\n".join(lines), reward

    def _handle_check_dependencies(self, action: IncidentAction) -> tuple:
        target = action.target.strip()
        s = self._scenario
        assert s is not None

        if target not in s.services:
            return (
                f"Unknown service: '{target}'.\n"
                f"Available services: {', '.join(s.service_names)}",
                0.0,
            )

        key = f"deps:{target}"
        is_new = key not in self._investigated
        self._investigated.add(key)

        dep_text = s.dependency_data.get(
            target, f"(No dependency info for {target})"
        )
        output = f"=== Dependencies for {target} ===\n{dep_text}"

        # Dependency checks give smaller reward (less direct evidence)
        if is_new and target in s.relevant_services():
            n_relevant = max(len(s.relevant_services()), 1)
            reward = s.reward_investigation / (n_relevant * 3)
        else:
            reward = 0.0

        return output, reward

    def _handle_diagnose(self, action: IncidentAction) -> tuple:
        s = self._scenario
        assert s is not None

        root_cause = action.parameters.get("root_cause", "").strip().lower()
        service = action.parameters.get("service", "").strip().lower()

        if self._diagnosis_submitted and self._diagnosis_correct:
            return "You already submitted a correct diagnosis. Proceed to remediation.", 0.0

        if not root_cause:
            return (
                "ERROR: 'diagnose' requires parameters: "
                '{"root_cause": "<your_diagnosis>"}.\n'
                'Optionally include "service": "<service_name>".',
                0.0,
            )

        # Build remediation hint for successful/partial diagnoses
        remediation_hint = (
            f"\nAvailable remediations: {', '.join(s.correct_remediations)}"
        )
        all_remediations = list(s.correct_remediations) + list(
            s.alternative_remediations.keys()
        )
        remediation_hint += f"\nAlternative options: {', '.join(all_remediations)}"

        # Exact match — full credit
        if root_cause == s.root_cause:
            self._diagnosis_submitted = True
            self._state.diagnosed = True
            self._diagnosis_correct = True
            return (
                f"CORRECT DIAGNOSIS: {root_cause}\n"
                f"Root cause confirmed in service '{s.root_cause_service}'.\n"
                f"Proceed with remediation.{remediation_hint}"
            ), s.reward_diagnosis

        # Fuzzy match — check if any keyword appears in the agent's diagnosis
        keywords = getattr(s, "root_cause_keywords", [])
        matched_keywords = [kw for kw in keywords if kw in root_cause]
        # Also check if the agent's diagnosis appears as a substring of the root cause or vice versa
        is_substring_match = (
            root_cause in s.root_cause or s.root_cause in root_cause
        )

        if matched_keywords or is_substring_match:
            # Good fuzzy match — right service implied, close enough cause
            self._diagnosis_submitted = True
            self._state.diagnosed = True
            self._diagnosis_correct = True
            credit = 0.80 if (service == s.root_cause_service or len(matched_keywords) >= 2) else 0.60
            return (
                f"DIAGNOSIS ACCEPTED: '{root_cause}' matches the root cause "
                f"(canonical: '{s.root_cause}').\n"
                f"Root cause is in service '{s.root_cause_service}'.\n"
                f"Proceed with remediation.{remediation_hint}"
            ), s.reward_diagnosis * credit

        # Right service, wrong cause — partial credit
        if service == s.root_cause_service:
            self._diagnosis_submitted = True
            self._state.diagnosed = True
            return (
                f"PARTIAL DIAGNOSIS: You identified the correct service "
                f"({service}) but the root cause '{root_cause}' is imprecise.\n"
                f"Partial credit awarded. Proceed with remediation.{remediation_hint}"
            ), s.reward_diagnosis * 0.33

        # Wrong
        return (
            f"INCORRECT DIAGNOSIS: '{root_cause}' does not match the evidence.\n"
            f"Consider re-investigating the affected services."
        ), -0.05

    def _handle_remediate(self, action: IncidentAction) -> tuple:
        s = self._scenario
        assert s is not None

        action_name = action.parameters.get("action", "").strip().lower()

        if not action_name:
            return (
                "ERROR: 'remediate' requires parameters: "
                '{"action": "<remediation_action>"}.',
                0.0,
            )

        if action_name in self._remediations_applied:
            return f"Already applied: '{action_name}'. Try a different action.", 0.0

        self._remediations_applied.append(action_name)
        per_action_budget = s.reward_remediation / max(
            len(s.correct_remediations), 1
        )

        # Exact correct remediation
        if action_name in s.correct_remediations:
            applied_correct = set(self._remediations_applied) & set(
                s.correct_remediations
            )
            self._state.remediated = len(applied_correct) == len(
                s.correct_remediations
            )

            if self._state.remediated:
                return (
                    f"REMEDIATION COMPLETE: Applied '{action_name}'.\n"
                    f"All required fixes in place. Incident resolved!"
                ), per_action_budget
            else:
                remaining = set(s.correct_remediations) - applied_correct
                return (
                    f"REMEDIATION PARTIAL: Applied '{action_name}' successfully.\n"
                    f"There are {len(remaining)} more fix(es) to apply."
                ), per_action_budget

        # Alternative remediation (partial credit)
        if action_name in s.alternative_remediations:
            credit = s.alternative_remediations[action_name]
            return (
                f"APPLIED (suboptimal): '{action_name}' — partial effect.\n"
                f"This helps but a more targeted fix exists."
            ), per_action_budget * credit

        # Fuzzy match — check if the action is close to a correct/alternative one
        all_known = list(s.correct_remediations) + list(
            s.alternative_remediations.keys()
        )
        # Check if any known remediation is a substring or shares significant words
        for known in all_known:
            known_words = set(known.split("_"))
            action_words = set(action_name.split("_"))
            overlap = known_words & action_words
            if len(overlap) >= 2 or known in action_name or action_name in known:
                # Treat as if agent meant this known remediation
                if known in s.correct_remediations:
                    self._remediations_applied[-1] = known  # fix the record
                    applied_correct = set(self._remediations_applied) & set(
                        s.correct_remediations
                    )
                    self._state.remediated = len(applied_correct) == len(
                        s.correct_remediations
                    )
                    status = "COMPLETE" if self._state.remediated else "PARTIAL"
                    return (
                        f"REMEDIATION {status}: Interpreted '{action_name}' as "
                        f"'{known}'. Applied successfully.\n"
                        f"{'Incident resolved!' if self._state.remediated else 'Continue remediation.'}"
                    ), per_action_budget
                elif known in s.alternative_remediations:
                    credit = s.alternative_remediations[known]
                    return (
                        f"APPLIED (suboptimal): Interpreted '{action_name}' as "
                        f"'{known}' — partial effect.\n"
                        f"A more targeted fix exists."
                    ), per_action_budget * credit

        # Truly wrong — show available options
        hint = f"\nAvailable actions: {', '.join(all_known)}"
        return (
            f"FAILED: '{action_name}' is not a recognised remediation.{hint}"
        ), -0.03

    def _handle_escalate(self, action: IncidentAction) -> tuple:
        s = self._scenario
        assert s is not None

        team = action.parameters.get("team", "unknown")
        reason = action.parameters.get("reason", "")

        # Escalation is valid if the agent is stuck on a hard scenario
        if s.difficulty == "hard" and not self._diagnosis_submitted:
            return (
                f"Escalated to team '{team}'. Senior on-call notified.\n"
                f"Partial credit granted. Continue investigating if possible."
            ), 0.02
        else:
            return (
                f"Unnecessary escalation to '{team}'. "
                f"You have enough information to proceed.\n"
                f"Try diagnosing or remediating instead."
            ), -0.02

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    def _investigation_reward(self, target: str, is_new: bool) -> float:
        """Compute reward for an investigation action."""
        s = self._scenario
        assert s is not None

        if not is_new:
            return 0.0  # already investigated this exact thing

        n_relevant = max(len(s.relevant_services()), 1)
        if target in s.relevant_services():
            # Budget split evenly across relevant services × 2 (logs + metrics)
            return s.reward_investigation / (n_relevant * 2)
        else:
            # Red herring / irrelevant — tiny reward for effort
            return 0.005

    def _check_done(self) -> bool:
        """Determine if the episode should end."""
        s = self._scenario
        assert s is not None
        st = self._state
        assert st is not None

        if st.remediated:
            return True
        if st.step_count >= s.max_steps:
            return True
        return False

    def _make_observation(
        self,
        command_output: str = "",
        reward: float = 0.0,
        done: bool = False,
    ) -> IncidentObservation:
        """Build an observation from the current scenario + state."""
        s = self._scenario
        assert s is not None
        st = self._state
        assert st is not None

        alerts = [AlertInfo(**a) for a in s.initial_alerts]
        services = [
            ServiceStatus(
                name=info.name,
                status=info.status,
                cpu=s.metrics_data.get(info.name, {}).get("cpu_pct", 0.0),
                memory=s.metrics_data.get(info.name, {}).get("memory_pct", 0.0),
                disk=s.metrics_data.get(info.name, {}).get("disk_usage_pct", 0.0),
                error_rate=s.metrics_data.get(info.name, {}).get(
                    "error_rate_pct", 0.0
                ),
            )
            for info in s.services.values()
        ]

        metadata = {
            "task_id": st.task_id,
            "difficulty": s.difficulty,
            "step": st.step_count,
            "max_steps": s.max_steps,
            "cumulative_reward": round(self._cumulative_reward, 4),
            "available_tasks": list_tasks(),
        }

        # Attach final score summary when episode ends
        if done:
            metadata["final_score"] = round(
                max(0.001, min(0.999, self._cumulative_reward)), 4
            )

        return IncidentObservation(
            alerts=alerts,
            services=services,
            command_output=command_output,
            available_commands=self.VALID_COMMANDS,
            timestamp=f"T+{st.time_elapsed_minutes}min",
            incident_summary=s.description,
            done=done,
            reward=reward,
            metadata=metadata,
        )
