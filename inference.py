"""
Baseline inference script for Incident Triage Environment.

Required by the hackathon submission checklist.  Uses the OpenAI-compatible
client, reads credentials from environment variables, and emits structured
[START] / [STEP] / [END] logs to stdout.

Environment variables
---------------------
API_BASE_URL : str   - LLM API endpoint  (default: https://api.openai.com/v1)
MODEL_NAME   : str   - model identifier  (default: gpt-4o-mini)
HF_TOKEN     : str   - Hugging Face / API key
SPACE_URL    : str   - URL of a running HF Space (e.g. https://user-incident-triage-env.hf.space)
IMAGE_NAME   : str   - Docker image name (fallback if SPACE_URL is not set)

Connection priority:
  1. SPACE_URL  -> connect to a running HF Space via HTTP/WebSocket
  2. IMAGE_NAME -> spin up a local Docker container

Usage::

    # Against a deployed HF Space
    export SPACE_URL=https://your-user-incident-triage-env.hf.space
    export API_BASE_URL=https://api.groq.com/openai/v1
    export MODEL_NAME=llama-3.3-70b-versatile
    export HF_TOKEN=gsk_...
    python inference.py

    # Against a local Docker container
    export IMAGE_NAME=incident-triage-env:latest
    export API_BASE_URL=https://api.groq.com/openai/v1
    export MODEL_NAME=llama-3.3-70b-versatile
    export HF_TOKEN=gsk_...
    python inference.py
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional

from openai import OpenAI

# -- Configuration from environment ------------------------------------------

API_BASE_URL: str = os.environ.get("API_BASE_URL", "https://api.openai.com/v1")
MODEL_NAME: str = os.environ.get("MODEL_NAME", "gpt-4o-mini")
API_KEY: str = os.environ.get("HF_TOKEN", os.environ.get("OPENAI_API_KEY", ""))
SPACE_URL: str = os.environ.get("SPACE_URL", "")
IMAGE_NAME: str = os.environ.get("IMAGE_NAME", "incident-triage-env:latest")

# -- Constants ---------------------------------------------------------------

BENCHMARK = "incident_triage_env"
TASKS: List[str] = [
    "easy_disk_full",
    "medium_cascading_timeout",
    "hard_memory_leak",
]
MAX_STEPS = 20
TEMPERATURE = 0.2
MAX_TOKENS = 1024
SUCCESS_SCORE_THRESHOLD = 0.5
MAX_TOTAL_REWARD = 1.0

SYSTEM_PROMPT = """\
You are an expert Site Reliability Engineer (SRE) performing on-call incident triage.

You receive observations about a production incident - alerts, service statuses,
and command output.  At each step you MUST respond with exactly ONE JSON object
(no markdown fences, no commentary):

{
  "command": "<check_logs|check_metrics|check_dependencies|diagnose|remediate|escalate>",
  "target": "<service-name>",
  "parameters": {}
}

For "diagnose":  {"root_cause": "<cause_id>", "service": "<svc_name>"}
For "remediate": {"action": "<remediation_action>"}
For "escalate":  {"team": "<team>", "reason": "<why>"}

Strategy
--------
1. Start by checking logs and metrics for the services mentioned in alerts.
2. Use check_dependencies to trace the causal chain upstream.
3. Look at memory_trend, cpu, error_rate, and log error messages to pinpoint root cause.
4. When confident, submit diagnose with root_cause and service.
5. Then apply remediate actions.  There may be more than one.
6. Red herrings exist - if a service's metrics look stable or the issue is a scheduled
   job, rule it out and move on.

Be systematic.  Follow the evidence.  Do NOT guess.
"""

# -- Structured logging (required format) ------------------------------------
# Format spec from hackathon:
#   [START] task=<task_name> env=<benchmark> model=<model_name>
#   [STEP]  step=<n> action=<action_str> reward=<0.00> done=<true|false> error=<msg|null>
#   [END]   success=<true|false> steps=<n> score=<score> rewards=<r1,r2,...,rn>


def log_start(*, task: str, env: str, model: str) -> None:
    """Emit [START] log entry."""
    print(f"[START] task={task} env={env} model={model}", flush=True)


def log_step(
    *,
    step: int,
    action: str,
    reward: float,
    done: bool,
    error: Optional[str] = None,
) -> None:
    """Emit [STEP] log entry."""
    error_val = error if error else "null"
    done_val = str(done).lower()
    print(
        f"[STEP] step={step} action={action} reward={reward:.2f} done={done_val} error={error_val}",
        flush=True,
    )


def log_end(
    *, success: bool, steps: int, score: float, rewards: List[float]
) -> None:
    """Emit [END] log entry."""
    rewards_str = ",".join(f"{r:.2f}" for r in rewards)
    print(
        f"[END] success={str(success).lower()} steps={steps} score={score:.3f} rewards={rewards_str}",
        flush=True,
    )


# -- LLM interaction --------------------------------------------------------


def get_model_response(
    client: OpenAI,
    step: int,
    last_output: str,
    last_reward: float,
    history: List[str],
    alerts_text: str,
) -> str:
    """Query the LLM for the next action."""
    recent = "\n".join(history[-8:])
    user_prompt = (
        f"Step {step}.\n\n"
        f"Active alerts:\n{alerts_text}\n\n"
        f"Last command output:\n{last_output}\n\n"
        f"Last reward: {last_reward:+.4f}\n\n"
        f"History:\n{recent}\n\n"
        f"What is your next action?  Respond with JSON only."
    )

    try:
        completion = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
            stream=False,
        )
        text = (completion.choices[0].message.content or "").strip()
        return text if text else '{"command":"check_logs","target":"api-server"}'
    except Exception as exc:
        print(f"[DEBUG] Model request failed: {exc}", file=sys.stderr, flush=True)
        return '{"command":"check_logs","target":"api-server"}'


def parse_action(text: str) -> Dict[str, Any]:
    """Parse LLM JSON output into an action dict with robust fallback."""
    cleaned = text.strip()
    if "```" in cleaned:
        parts = cleaned.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{"):
                cleaned = part
                break

    try:
        data = json.loads(cleaned)
        if isinstance(data, dict) and "command" in data:
            params = data.get("parameters", {})
            if isinstance(params, dict):
                data["parameters"] = {
                    k: str(v) if not isinstance(v, str) else v
                    for k, v in params.items()
                }
            else:
                data["parameters"] = {}
            return data
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{[^{}]+\}", cleaned)
    if match:
        try:
            data = json.loads(match.group())
            params = data.get("parameters", {})
            if isinstance(params, dict):
                data["parameters"] = {
                    k: str(v) if not isinstance(v, str) else v
                    for k, v in params.items()
                }
            else:
                data["parameters"] = {}
            return data
        except json.JSONDecodeError:
            pass

    return {"command": "check_logs", "target": "api-server", "parameters": {}}


def format_alerts(obs_data: Any) -> str:
    """Build a human-readable alert summary from an observation."""
    alerts = getattr(obs_data, "alerts", [])
    if not alerts:
        return "(no alerts)"
    lines = []
    for a in alerts:
        sev = getattr(a, "severity", "?")
        svc = getattr(a, "service", "?")
        msg = getattr(a, "message", "")
        lines.append(f"  [{sev.upper()}] {svc}: {msg}")
    return "\n".join(lines)


# -- Environment connection --------------------------------------------------


async def connect_env():
    """Connect to the environment via Space URL or Docker image.

    Priority:
      1. SPACE_URL env var -> connect to running HF Space
      2. IMAGE_NAME env var -> launch local Docker container
    """
    from incident_triage_env import IncidentTriageEnv

    if SPACE_URL:
        print(
            f"[DEBUG] Connecting to HF Space: {SPACE_URL}",
            file=sys.stderr,
            flush=True,
        )
        return IncidentTriageEnv(base_url=SPACE_URL)
    else:
        print(
            f"[DEBUG] Launching Docker container: {IMAGE_NAME}",
            file=sys.stderr,
            flush=True,
        )
        return await IncidentTriageEnv.from_docker_image(IMAGE_NAME)


# -- Main loop ---------------------------------------------------------------


async def run_task(task_id: str, client: OpenAI, env) -> float:
    """Run a single task and return the normalised score."""
    from incident_triage_env import IncidentAction

    history: List[str] = []
    rewards: List[float] = []
    steps_taken = 0
    score = 0.0
    success = False

    log_start(task=task_id, env=BENCHMARK, model=MODEL_NAME)

    try:
        result = await env.reset(task_id=task_id)
        last_output: str = result.observation.command_output
        last_reward: float = 0.0
        alerts_text: str = format_alerts(result.observation)

        for step in range(1, MAX_STEPS + 1):
            if result.done:
                break

            raw_response = get_model_response(
                client, step, last_output, last_reward, history, alerts_text
            )
            action_data = parse_action(raw_response)

            action = IncidentAction(
                command=action_data.get("command", "check_logs"),
                target=action_data.get("target", ""),
                parameters=action_data.get("parameters", {}),
            )

            result = await env.step(action)

            reward = result.reward or 0.0
            done = result.done

            rewards.append(reward)
            steps_taken = step
            last_output = result.observation.command_output
            last_reward = reward

            log_step(
                step=step,
                action=json.dumps(action_data),
                reward=reward,
                done=done,
                error=None,
            )

            history.append(
                f"Step {step}: {action.command} {action.target} "
                f"-> reward {reward:+.4f}{' [DONE]' if done else ''}"
            )

            if done:
                break

        score = sum(rewards) / MAX_TOTAL_REWARD if MAX_TOTAL_REWARD > 0 else 0.0
        score = max(0.001, min(0.999, score))
        success = score >= SUCCESS_SCORE_THRESHOLD

    finally:
        log_end(success=success, steps=steps_taken, score=score, rewards=rewards)

    return score


async def main() -> None:
    """Run all tasks sequentially and report aggregate scores."""
    client = OpenAI(base_url=API_BASE_URL, api_key=API_KEY)

    env = await connect_env()

    try:
        scores: Dict[str, float] = {}
        for task_id in TASKS:
            print(
                f"\n{'='*60}\n  Running task: {task_id}\n{'='*60}",
                file=sys.stderr,
                flush=True,
            )
            score = await run_task(task_id, client, env)
            scores[task_id] = score
            print(
                f"[DEBUG] Task '{task_id}' finished - score: {score:.4f}",
                file=sys.stderr,
                flush=True,
            )

        avg = sum(scores.values()) / len(scores) if scores else 0.0
        print(f"\n[DEBUG] === FINAL RESULTS ===", file=sys.stderr, flush=True)
        for tid, sc in scores.items():
            print(f"[DEBUG]   {tid}: {sc:.4f}", file=sys.stderr, flush=True)
        print(f"[DEBUG]   Average: {avg:.4f}", file=sys.stderr, flush=True)
    finally:
        try:
            await env.close()
        except Exception as e:
            print(
                f"[DEBUG] env.close() error: {e}",
                file=sys.stderr,
                flush=True,
            )


if __name__ == "__main__":
    asyncio.run(main())
