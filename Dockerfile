# ---- Stage 1: Builder ----
FROM ghcr.io/meta-pytorch/openenv-base:latest AS builder

WORKDIR /app

# Ensure uv is available
RUN command -v uv >/dev/null 2>&1 || pip install uv

# Install git (needed for some dependency resolution)
RUN apt-get update && apt-get install -y --no-install-recommends git && \
    rm -rf /var/lib/apt/lists/*

# Copy dependency specification first (Docker layer cache)
COPY pyproject.toml uv.lock ./

# Create venv and install dependencies only
RUN uv sync --frozen --no-install-project 2>/dev/null || \
    uv sync --no-install-project

# Copy full source
COPY . .

# Install the project itself
RUN uv sync --frozen 2>/dev/null || uv sync

# ---- Stage 2: Runtime ----
FROM ghcr.io/meta-pytorch/openenv-base:latest

WORKDIR /app

# Copy virtualenv and application code from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app /app

# Make sure venv is on PATH
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app:$PYTHONPATH"

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import requests; r=requests.get('http://localhost:8000/health'); assert r.status_code==200"

CMD ["uvicorn", "incident_triage_env.server.app:app", "--host", "0.0.0.0", "--port", "8000"]
