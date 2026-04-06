"""
Easy scenario: Production API server disk full.

Single service, single root cause, obvious log evidence.
Optimal path: check_logs api-server -> check_metrics api-server -> diagnose -> remediate
"""

from .registry import Scenario, ServiceInfo, register_task

scenario = Scenario(
    task_id="easy_disk_full",
    difficulty="easy",
    title="Production API Server Disk Full",
    description=(
        "INCIDENT: The production API server is returning HTTP 500 errors to "
        "customers. Monitoring has fired a critical alert for disk usage on the "
        "api-server host. Investigate the root cause, diagnose the issue, and "
        "apply the appropriate remediation."
    ),
    services={
        "api-server": ServiceInfo(
            name="api-server",
            status="degraded",
            logs="",
            metrics={},
            dependencies=["postgres-primary", "redis-cache"],
        ),
        "postgres-primary": ServiceInfo(
            name="postgres-primary",
            status="healthy",
            logs="",
            metrics={},
            dependencies=[],
        ),
        "redis-cache": ServiceInfo(
            name="redis-cache",
            status="healthy",
            logs="",
            metrics={},
            dependencies=[],
        ),
    },
    initial_alerts=[
        {
            "severity": "critical",
            "service": "api-server",
            "message": "Disk usage at 98% on /var/log partition",
            "timestamp": "14:32",
        },
        {
            "severity": "warning",
            "service": "api-server",
            "message": "HTTP 500 error rate > 5% (currently 8.2%)",
            "timestamp": "14:33",
        },
    ],
    log_data={
        "api-server": (
            "[14:30:01] INFO  Request handled: GET /api/users -> 200 (12ms)\n"
            "[14:30:45] INFO  Request handled: POST /api/orders -> 201 (34ms)\n"
            "[14:31:15] ERROR OSError: [Errno 28] No space left on device: '/var/log/api/access.log'\n"
            "[14:31:15] ERROR Failed to write access log entry, switching to stderr\n"
            "[14:31:22] ERROR OSError: [Errno 28] No space left on device: '/var/log/api/error.log'\n"
            "[14:31:30] WARN  Log rotation config missing: /etc/logrotate.d/api not found\n"
            "[14:32:00] CRITICAL Application entering degraded mode — disk write failures cascading\n"
            "[14:32:05] ERROR HTTP 500 returned for GET /api/orders — cannot persist request log\n"
            "[14:32:10] ERROR HTTP 500 returned for POST /api/checkout — write failure\n"
            "[14:32:30] INFO  Disk usage breakdown:\n"
            "[14:32:30] INFO    /var/log/api/access.log.2025-01-15    890 MB\n"
            "[14:32:30] INFO    /var/log/api/access.log.2025-06-20    1.2 GB\n"
            "[14:32:30] INFO    /var/log/api/access.log               3.8 GB\n"
            "[14:32:30] INFO    Total /var/log usage: 49.1 GB of 50 GB\n"
        ),
        "postgres-primary": (
            "[14:30:00] LOG  checkpoint complete: wrote 128 buffers (0.6%)\n"
            "[14:31:00] LOG  automatic vacuum of table 'public.orders': removed 45 dead tuples\n"
            "[14:32:00] LOG  checkpoint complete: wrote 96 buffers (0.4%)\n"
            "[14:32:30] LOG  connection stats: 42 active / 500 max\n"
        ),
        "redis-cache": (
            "[14:30:00] * Server started, Redis version=7.2.0\n"
            "[14:31:00] # DB 0: 1523 keys (0 volatile) in 4096 slots HT\n"
            "[14:32:00] * Background saving started by pid 1234\n"
            "[14:32:01] * Background saving terminated with success\n"
        ),
    },
    metrics_data={
        "api-server": {
            "cpu_pct": 14.0,
            "memory_pct": 42.0,
            "disk_usage_pct": 98.2,
            "requests_per_sec": 150,
            "error_rate_pct": 8.2,
            "p99_latency_ms": 450,
            "open_file_descriptors": 312,
        },
        "postgres-primary": {
            "cpu_pct": 25.0,
            "memory_pct": 60.0,
            "disk_usage_pct": 42.0,
            "connections_active": 42,
            "connections_max": 500,
            "query_time_avg_ms": 12,
            "replication_lag_bytes": 0,
        },
        "redis-cache": {
            "cpu_pct": 5.0,
            "memory_pct": 30.0,
            "disk_usage_pct": 10.0,
            "hit_rate_pct": 94.0,
            "connected_clients": 12,
            "evictions_per_sec": 0,
        },
    },
    dependency_data={
        "api-server": (
            "Upstream dependencies:\n"
            "  - postgres-primary (primary datastore, TCP 5432)\n"
            "  - redis-cache (session store + rate-limiting, TCP 6379)\n"
            "Downstream consumers:\n"
            "  - load-balancer (health-check on :8080/healthz)"
        ),
        "postgres-primary": (
            "Upstream dependencies: none\n"
            "Downstream consumers:\n"
            "  - api-server (read/write, pool size 50)\n"
            "  - analytics-worker (read replica preferred)"
        ),
        "redis-cache": (
            "Upstream dependencies: none\n"
            "Downstream consumers:\n"
            "  - api-server (sessions, rate-limits)\n"
            "  - background-workers (job queue)"
        ),
    },
    root_cause="disk_full_var_log",
    root_cause_service="api-server",
    root_cause_keywords=["disk_full", "disk", "no_space", "space", "log_full", "var_log"],
    correct_remediations=["clear_old_logs", "configure_log_rotation"],
    alternative_remediations={
        "restart_service": 0.15,
        "resize_disk": 0.40,
        "delete_old_logs": 0.80,
        "increase_disk_space": 0.40,
        "add_log_rotation": 0.80,
        "enable_log_rotation": 0.80,
        "clean_logs": 0.80,
        "remove_old_logs": 0.80,
        "truncate_logs": 0.60,
    },
    max_steps=10,
    optimal_steps=4,
    red_herring_services=set(),
)

register_task(scenario)
