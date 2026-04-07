---
title: Incident Triage Env
emoji: 🚨
colorFrom: red
colorTo: gray
sdk: docker
app_port: 8000
---

# Incident Triage Environment for OpenEnv

An AI agent plays the role of an on-call **Site Reliability Engineer (SRE)**.
It receives production alerts, investigates service logs / metrics /
dependencies, diagnoses root causes, and applies remediations — exactly what
human SREs do during real incidents.

Built on the [OpenEnv](https://github.com/meta-pytorch/OpenEnv) framework
(`step()` / `reset()` / `state()` API).

---

## Motivation

On-call incident response is one of the most common and high-stakes tasks in
software engineering.  Engineers must quickly triage noisy alerts, trace
dependency chains across microservices, distinguish root causes from symptoms,
and apply the correct fix under time pressure.

This environment captures that workflow as a reinforcement-learning problem
with rich, multi-step observations and partial-credit reward shaping — making
it useful for both training and evaluating agentic LLMs.

---

## Action Space

| Command | `target` | `parameters` | Description |
|---------|----------|------------|-------------|
| `check_logs` | service name | — | View recent log output |
| `check_metrics` | service name | — | View CPU / memory / disk / error-rate metrics |
| `check_dependencies` | service name | — | View upstream & downstream service dependencies |
| `diagnose` | — | `{"root_cause": "...", "service": "..."}` | Submit root-cause diagnosis |
| `remediate` | — | `{"action": "..."}` | Apply a remediation action |
| `escalate` | — | `{"team": "...", "reason": "..."}` | Escalate to another team |

### Action model (Pydantic)

```python
class IncidentAction(Action):
    command: str                         # one of the above
    target: str = ""                     # service name
    parameters: Dict[str, str] = {}      # command-specific
```

---

## Observation Space

| Field | Type | Description |
|-------|------|-------------|
| `alerts` | `List[AlertInfo]` | Active monitoring alerts (severity, service, message) |
| `services` | `List[ServiceStatus]` | Health snapshot of every service (cpu, memory, disk, error_rate) |
| `command_output` | `str` | Text result of the last command |
| `available_commands` | `List[str]` | Valid commands |
| `timestamp` | `str` | Simulated wall-clock offset (e.g. `T+9min`) |
| `incident_summary` | `str` | Human-readable incident description |
| `done` | `bool` | Whether the episode has ended |
| `reward` | `float` | Per-step reward signal |
| `metadata` | `dict` | Includes `task_id`, `step`, `cumulative_reward`, `available_tasks` |

---

## Tasks

| Task ID | Difficulty | Description | Optimal Steps | Services |
|---------|------------|-------------|:-------------:|:--------:|
| `easy_disk_full` | Easy | API server `/var/log` partition full, causing 500 errors | 4 | 3 |
| `medium_cascading_timeout` | Medium | Missing DB index causes cascading timeouts across 4 services | 7 | 5 |
| `hard_memory_leak` | Hard | Memory leak in webhook handler with misleading CPU spike on unrelated service | 10 | 6 |

### Difficulty progression

- **Easy:** Single service, single alert, obvious root cause in logs.
- **Medium:** Multi-service dependency chain, multiple alerts, one red herring.
- **Hard:** Ambiguous signals, two OOM-killed services, two red herrings (scheduled job + healthy cache), requires correlating memory trends across time.

---

## Reward Design

Rewards sum to a maximum of **1.0** per episode:

| Category | Budget | How distributed |
|----------|:------:|----------------|
| Investigation | 0.20 | Split across relevant `(command, service)` pairs; first check earns reward, repeats earn 0 |
| Diagnosis | 0.30 | Full for exact match, 33% for correct service / wrong cause, −0.05 for wrong |
| Remediation | 0.40 | Split across correct actions; alternative remediations get partial credit |
| Efficiency bonus | 0.10 | Proportional to `1 − (steps − optimal) / max_steps`, awarded at episode end |

Negative rewards (wrong diagnosis, wrong remediation) can reduce the score but
the final score is always clamped to `[0.0, 1.0]`.

---

## Baseline Scores

| Task | Expected Score | Steps |
|------|:--------------:|:-----:|
| `easy_disk_full` | ~0.80 | 5 |
| `medium_cascading_timeout` | ~0.45 | 10 |
| `hard_memory_leak` | ~0.20 | 15 |

---

## Setup & Usage

### Docker (recommended)

```bash
docker build -t incident-triage-env .
docker run -p 8000:8000 incident-triage-env
```

### Local development

```bash
pip install -e ".[dev]"
python -m incident_triage_env.server.app
# Server runs at http://localhost:8000
```

### Run inference

```bash
export API_BASE_URL=https://api.openai.com/v1
export MODEL_NAME=gpt-4o-mini
export HF_TOKEN=sk-...
python inference.py
```

### Verify

```bash
# Pre-submission checks
openenv validate                              # local structure
openenv validate --url http://localhost:8000   # running server
```

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `API_BASE_URL` | LLM API endpoint |
| `MODEL_NAME` | Model identifier for inference |
| `HF_TOKEN` | Hugging Face / API key |

---

## Project Structure

```
incident-triage-env/
├── openenv.yaml              # OpenEnv manifest
├── pyproject.toml            # Package metadata & dependencies
├── uv.lock                   # Dependency lockfile
├── Dockerfile                # Multi-stage Docker build
├── inference.py              # Baseline inference script
├── README.md
├── __init__.py               # Package exports (incident_triage_env)
├── models.py                 # Action / Observation / State types
├── client.py                 # EnvClient subclass
├── scenarios/
│   ├── registry.py           # Task registry & Scenario dataclass
│   ├── easy_disk_full.py     # Task 1: disk full (easy)
│   ├── medium_cascading_timeout.py  # Task 2: cascading timeout (medium)
│   └── hard_memory_leak.py   # Task 3: memory leak (hard)
└── server/
    ├── app.py                # FastAPI app + main() entry point
    ├── environment.py        # Core environment logic
    └── rubrics.py            # Reward rubric (trajectory-based)
```
