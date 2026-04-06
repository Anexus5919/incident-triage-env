"""
Data models for Incident Triage Environment.

This module defines the Action, Observation, and State types for SRE incident
triage via the OpenEnv interface. An AI agent receives alerts, investigates
services, diagnoses root causes, and remediates production incidents.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from openenv.core.env_server import Action, Observation, State


class AlertInfo(BaseModel):
    """A single alert fired by the monitoring system."""

    severity: str = "warning"  # "critical", "warning", "info"
    service: str = ""
    message: str = ""
    timestamp: str = ""


class ServiceStatus(BaseModel):
    """Health status snapshot of a single service."""

    name: str = ""
    status: str = "healthy"  # "healthy", "degraded", "down"
    cpu: float = 0.0
    memory: float = 0.0
    disk: float = 0.0
    error_rate: float = 0.0


class IncidentAction(Action):
    """
    Action for Incident Triage environment.

    Attributes:
        command: The action type to execute.
            Valid commands: "check_logs", "check_metrics", "check_dependencies",
            "diagnose", "remediate", "escalate"
        target: Service name to target (e.g. "api-server", "postgres-primary").
        parameters: Additional parameters for the command.
            For "diagnose": {"root_cause": "<cause_id>", "service": "<svc>"}
            For "remediate": {"action": "<remediation_action>"}
            For "escalate": {"team": "<team>", "reason": "<reason>"}
    """

    command: str
    target: str = ""
    parameters: Dict[str, str] = Field(default_factory=dict)


class IncidentObservation(Observation):
    """
    Observation for Incident Triage environment.

    Inherits ``done``, ``reward``, and ``metadata`` from base Observation.

    Attributes:
        alerts: Currently active alerts.
        services: Health status of all visible services.
        command_output: Text output from the last command executed.
        available_commands: Valid commands the agent can issue.
        timestamp: Simulated wall-clock offset since incident start.
        incident_summary: Brief human-readable incident description.
    """

    alerts: List[AlertInfo] = Field(default_factory=list)
    services: List[ServiceStatus] = Field(default_factory=list)
    command_output: str = ""
    available_commands: List[str] = Field(default_factory=list)
    timestamp: str = "T+0min"
    incident_summary: str = ""


class IncidentState(State):
    """
    State for Incident Triage environment.

    Inherits ``episode_id`` and ``step_count`` from base State.

    Attributes:
        task_id: Which scenario is currently active.
        diagnosed: Whether the agent submitted a correct diagnosis.
        remediated: Whether correct remediation was fully applied.
        actions_taken: Chronological history of commands issued.
        time_elapsed_minutes: Simulated minutes since incident start.
        investigated_services: Services the agent has inspected so far.
    """

    task_id: str = ""
    diagnosed: bool = False
    remediated: bool = False
    actions_taken: List[str] = Field(default_factory=list)
    time_elapsed_minutes: int = 0
    investigated_services: List[str] = Field(default_factory=list)
