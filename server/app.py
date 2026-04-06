"""
FastAPI application for the Incident Triage Environment.

Exposes the environment over HTTP and WebSocket endpoints.
"""

from openenv.core.env_server import create_app

from ..models import IncidentAction, IncidentObservation
from .environment import IncidentTriageEnvironment

# Pass the CLASS (not an instance) for per-session WebSocket support.
app = create_app(
    IncidentTriageEnvironment,
    IncidentAction,
    IncidentObservation,
    env_name="incident_triage_env",
)


def main() -> None:
    """Entry point for the ``server`` console_script (see pyproject.toml)."""
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
