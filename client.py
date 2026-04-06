"""
Incident Triage Environment Client.

Connects to a running environment server over WebSocket and translates
between typed Python objects and JSON payloads.  Follows the same pattern
as ``chess_env.client.ChessEnv``.
"""

from __future__ import annotations

from typing import Any, Dict

from openenv.core.client_types import StepResult
from openenv.core.env_client import EnvClient

from .models import (
    AlertInfo,
    IncidentAction,
    IncidentObservation,
    IncidentState,
    ServiceStatus,
)


class IncidentTriageEnv(EnvClient[IncidentAction, IncidentObservation, IncidentState]):
    """
    Client for Incident Triage Environment.

    Example (async — recommended)::

        async with IncidentTriageEnv(base_url="http://localhost:8000") as env:
            result = await env.reset(task_id="easy_disk_full")
            print(result.observation.alerts)

            result = await env.step(
                IncidentAction(command="check_logs", target="api-server")
            )
            print(result.observation.command_output)

    Example (sync wrapper)::

        with IncidentTriageEnv(base_url="http://localhost:8000").sync() as env:
            result = env.reset(task_id="easy_disk_full")
            result = env.step(
                IncidentAction(command="check_logs", target="api-server")
            )

    Example (Docker)::

        env = await IncidentTriageEnv.from_docker_image("incident-triage-env:latest")
        try:
            result = await env.reset(task_id="medium_cascading_timeout")
            ...
        finally:
            await env.close()
    """

    def _step_payload(self, action: IncidentAction) -> Dict[str, Any]:
        """Serialise an ``IncidentAction`` into a JSON-compatible dict."""
        return {
            "command": action.command,
            "target": action.target,
            "parameters": action.parameters,
        }

    def _parse_result(
        self, payload: Dict[str, Any]
    ) -> StepResult[IncidentObservation]:
        """Deserialise a server JSON response into a ``StepResult``."""
        obs_data = payload.get("observation", {})

        alerts = [AlertInfo(**a) for a in obs_data.get("alerts", [])]
        services = [ServiceStatus(**s) for s in obs_data.get("services", [])]

        observation = IncidentObservation(
            alerts=alerts,
            services=services,
            command_output=obs_data.get("command_output", ""),
            available_commands=obs_data.get("available_commands", []),
            timestamp=obs_data.get("timestamp", "T+0min"),
            incident_summary=obs_data.get("incident_summary", ""),
            done=obs_data.get("done", False),
            reward=obs_data.get("reward", 0.0),
            metadata=obs_data.get("metadata", {}),
        )

        return StepResult(
            observation=observation,
            reward=observation.reward,
            done=observation.done,
        )

    def _parse_state(self, payload: Dict[str, Any]) -> IncidentState:
        """Deserialise the ``/state`` endpoint response."""
        return IncidentState(
            episode_id=payload.get("episode_id", ""),
            step_count=payload.get("step_count", 0),
            task_id=payload.get("task_id", ""),
            diagnosed=payload.get("diagnosed", False),
            remediated=payload.get("remediated", False),
            actions_taken=payload.get("actions_taken", []),
            time_elapsed_minutes=payload.get("time_elapsed_minutes", 0),
            investigated_services=payload.get("investigated_services", []),
        )
