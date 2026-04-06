"""
Hard scenario: Intermittent OOM kills with misleading signals.

payment-service has a memory leak in its Stripe webhook handler (HTTP response
objects not released).  notification-service also OOM-kills because it calls
back into payment-service and gets backed-up.  analytics-worker has a
*scheduled* CPU spike from a daily aggregation job — a red herring.  redis-cache
is perfectly healthy — another red herring.

Optimal path (10 steps):
  check_logs payment-service -> check_metrics payment-service ->
  check_logs notification-service -> check_dependencies notification-service ->
  check_logs analytics-worker (rule out) -> check_metrics analytics-worker (confirm) ->
  check_logs rabbitmq -> check_metrics rabbitmq ->
  diagnose -> remediate (x2)
"""

from .registry import Scenario, ServiceInfo, register_task

scenario = Scenario(
    task_id="hard_memory_leak",
    difficulty="hard",
    title="Intermittent OOM Kills with Misleading Signals",
    description=(
        "INCIDENT: Two services have been OOM-killed and auto-restarted in the "
        "last 2 hours. A third service is showing a sustained CPU spike > 90%. "
        "The RabbitMQ notification queue is backing up. Alerts are noisy and "
        "potentially misleading.\n\n"
        "Your task: correlate metrics across services and time windows, "
        "distinguish the real root cause from red herrings, and apply the "
        "correct fix."
    ),
    services={
        "payment-service": ServiceInfo(
            name="payment-service",
            status="degraded",
            dependencies=["postgres-primary", "rabbitmq", "redis-cache"],
        ),
        "notification-service": ServiceInfo(
            name="notification-service",
            status="down",
            dependencies=["rabbitmq", "redis-cache", "payment-service"],
        ),
        "analytics-worker": ServiceInfo(
            name="analytics-worker",
            status="degraded",
            dependencies=["postgres-primary", "redis-cache"],
        ),
        "postgres-primary": ServiceInfo(
            name="postgres-primary",
            status="healthy",
            dependencies=[],
        ),
        "rabbitmq": ServiceInfo(
            name="rabbitmq",
            status="healthy",
            dependencies=[],
        ),
        "redis-cache": ServiceInfo(
            name="redis-cache",
            status="healthy",
            dependencies=[],
        ),
    },
    initial_alerts=[
        {
            "severity": "critical",
            "service": "payment-service",
            "message": "OOM killed by kernel (3rd time in 2 hours). Auto-restarted.",
            "timestamp": "03:42",
        },
        {
            "severity": "critical",
            "service": "notification-service",
            "message": "OOM killed — service currently DOWN, restart pending.",
            "timestamp": "03:38",
        },
        {
            "severity": "warning",
            "service": "analytics-worker",
            "message": "CPU usage > 90% sustained for 15 minutes",
            "timestamp": "03:35",
        },
        {
            "severity": "warning",
            "service": "rabbitmq",
            "message": "Queue 'notifications' depth: 15 200 messages, consumer lag increasing",
            "timestamp": "03:39",
        },
        {
            "severity": "warning",
            "service": "payment-service",
            "message": "Response latency p99 > 5 s",
            "timestamp": "03:40",
        },
    ],
    log_data={
        "payment-service": (
            "[03:00:00] INFO  Memory usage: 512 MB / 2048 MB (25%)\n"
            "[03:10:00] INFO  Memory usage: 780 MB / 2048 MB (38%)\n"
            "[03:15:00] INFO  Processing Stripe webhook batch: 450 events queued\n"
            "[03:15:01] DEBUG WebhookHandler: allocating HTTP response buffer per event\n"
            "[03:20:00] WARN  Memory usage: 1200 MB / 2048 MB (58%) — GC pause 1.8 s\n"
            "[03:25:01] DEBUG WebhookHandler: processed 450 events, but response objects not released\n"
            "[03:30:00] WARN  Memory usage: 1650 MB / 2048 MB (80%) — GC unable to reclaim\n"
            "[03:35:00] ERROR Memory usage: 1920 MB / 2048 MB (93%)\n"
            "[03:35:01] WARN  Heap dump: 12 000 unreleased HTTP response objects in webhook_handler\n"
            "[03:40:00] ERROR Memory usage: 2010 MB / 2048 MB (98%)\n"
            "[03:42:00] FATAL OOM: Killed by kernel OOM killer (oom_score_adj=950)\n"
            "[03:42:05] INFO  Service restarted by systemd (3rd restart in 2 h)\n"
            "[03:42:10] INFO  Memory usage post-restart: 480 MB / 2048 MB (23%)\n"
        ),
        "notification-service": (
            "[03:30:00] INFO  Memory usage: 400 MB / 1024 MB (39%)\n"
            "[03:33:00] INFO  Consuming from rabbitmq queue 'notifications'\n"
            "[03:34:00] INFO  For each notification, calling payment-service /api/confirm\n"
            "[03:35:00] WARN  Memory usage: 850 MB / 1024 MB (83%)\n"
            "[03:35:30] WARN  payment-service /api/confirm responding slowly (p99 4.2 s)\n"
            "[03:36:00] WARN  Backed-up response buffers: 8000 in-flight HTTP calls to payment-service\n"
            "[03:37:00] ERROR Memory usage: 980 MB / 1024 MB (95%)\n"
            "[03:38:00] FATAL OOM: Killed (oom_score_adj=880)\n"
            "[03:38:05] INFO  Service restart initiated\n"
            "[03:38:10] INFO  Memory post-restart: 200 MB / 1024 MB (19%)\n"
            "[03:38:15] WARN  Consuming backed-up messages — each triggers payment-service callback\n"
        ),
        "analytics-worker": (
            "[03:20:00] INFO  === Starting scheduled daily aggregation job ===\n"
            "[03:25:00] INFO  Processing 2.1 M order records for daily report\n"
            "[03:30:00] INFO  CPU-intensive aggregation: 45% through dataset\n"
            "[03:35:00] INFO  CPU-intensive aggregation: 78% through dataset\n"
            "[03:40:00] INFO  Aggregation COMPLETE. Peak CPU: 94%. Memory STABLE at 1.1 GB.\n"
            "[03:40:01] INFO  Results written to analytics_daily table. Job finished.\n"
            "[03:40:02] INFO  CPU returning to baseline (8%)\n"
        ),
        "postgres-primary": (
            "[03:30:00] LOG  checkpoint complete: wrote 256 buffers (1.2%)\n"
            "[03:35:00] LOG  connection count: 120/500 — normal\n"
            "[03:40:00] LOG  checkpoint complete: wrote 312 buffers (1.5%)\n"
            "[03:42:00] LOG  connection count: 115/500 — normal\n"
        ),
        "rabbitmq": (
            "[03:30:00] INFO  Queue 'notifications': 2000 messages, 3 consumers\n"
            "[03:35:00] INFO  Queue 'notifications': 8000 messages, 2 consumers\n"
            "[03:38:00] WARN  Queue 'notifications': 15 000 messages, 1 consumer "
            "(notification-service disconnected)\n"
            "[03:39:00] WARN  Queue 'notifications': 15 200 messages, consumer rate: 50/s\n"
            "[03:40:00] INFO  Consumer reconnected (notification-service). Drain rate increasing.\n"
            "[03:42:00] INFO  Queue 'notifications': 12 000 messages, 2 consumers, draining\n"
        ),
        "redis-cache": (
            "[03:30:00] # Memory: 800 MB / 4 GB (20%)\n"
            "[03:35:00] # Memory: 810 MB / 4 GB (20%) — stable\n"
            "[03:40:00] # Memory: 805 MB / 4 GB (20%) — stable\n"
            "[03:42:00] # Hit rate: 96%. Connected clients: 28. No anomalies.\n"
        ),
    },
    metrics_data={
        "payment-service": {
            "cpu_pct": 45.0,
            "memory_pct": 94.0,
            "disk_usage_pct": 30.0,
            "error_rate_pct": 5.0,
            "memory_trend_1h_pct": [25, 38, 58, 80, 93, 98],
            "gc_pause_avg_ms": 1800,
            "heap_live_objects": 12000,
            "webhook_queue_depth": 450,
            "oom_kills_last_2h": 3,
            "p99_latency_ms": 5200,
        },
        "notification-service": {
            "cpu_pct": 0.0,
            "memory_pct": 0.0,
            "disk_usage_pct": 20.0,
            "error_rate_pct": 100.0,
            "status": "DOWN (OOM killed, restarting)",
            "memory_before_crash_pct": 95.0,
            "restarts_last_2h": 2,
            "inflight_http_calls_at_crash": 8000,
        },
        "analytics-worker": {
            "cpu_pct": 92.0,
            "memory_pct": 55.0,
            "disk_usage_pct": 40.0,
            "error_rate_pct": 0.5,
            "memory_trend_1h_pct": [52, 53, 54, 55, 55, 55],
            "job_status": "daily_aggregation (78% complete)",
            "job_scheduled_at": "03:20 UTC daily",
        },
        "postgres-primary": {
            "cpu_pct": 30.0,
            "memory_pct": 65.0,
            "disk_usage_pct": 50.0,
            "error_rate_pct": 0.0,
            "connections_active": 120,
            "connections_max": 500,
            "replication_lag_bytes": 0,
        },
        "rabbitmq": {
            "cpu_pct": 20.0,
            "memory_pct": 40.0,
            "disk_usage_pct": 15.0,
            "error_rate_pct": 0.0,
            "queue_depth_notifications": 15200,
            "consumer_count": 2,
            "publish_rate_per_sec": 120,
            "deliver_rate_per_sec": 50,
        },
        "redis-cache": {
            "cpu_pct": 10.0,
            "memory_pct": 20.0,
            "disk_usage_pct": 8.0,
            "error_rate_pct": 0.0,
            "hit_rate_pct": 96.0,
            "connected_clients": 28,
            "evictions_per_sec": 0,
        },
    },
    dependency_data={
        "payment-service": (
            "Upstream dependencies:\n"
            "  - postgres-primary (transaction records, port 5432)\n"
            "  - rabbitmq (publishes payment events to 'notifications' queue)\n"
            "  - redis-cache (idempotency keys, rate limiting)\n"
            "External:\n"
            "  - Receives Stripe webhook HTTP callbacks (inbound)\n"
            "Downstream consumers:\n"
            "  - notification-service calls POST /api/confirm for each notification"
        ),
        "notification-service": (
            "Upstream dependencies:\n"
            "  - rabbitmq (consumes 'notifications' queue)\n"
            "  - redis-cache (dedup check)\n"
            "  - payment-service (calls /api/confirm per notification — SYNCHRONOUS)\n"
            "NOTE: If payment-service is slow, notification-service backs up"
        ),
        "analytics-worker": (
            "Upstream dependencies:\n"
            "  - postgres-primary (read-only aggregation queries)\n"
            "  - redis-cache (intermediate result caching)\n"
            "Scheduled:\n"
            "  - Daily aggregation job runs at 03:20 UTC (CPU-heavy, ~20 min)"
        ),
        "postgres-primary": (
            "Upstream dependencies: none\n"
            "Downstream consumers:\n"
            "  - payment-service, analytics-worker, order-service"
        ),
        "rabbitmq": (
            "Upstream dependencies: none\n"
            "Downstream consumers:\n"
            "  - notification-service (queue: 'notifications')\n"
            "  - payment-service (publisher)"
        ),
        "redis-cache": (
            "Upstream dependencies: none\n"
            "Downstream consumers:\n"
            "  - payment-service, notification-service, analytics-worker\n"
            "Status: completely healthy, no anomalies"
        ),
    },
    root_cause="memory_leak_webhook_handler",
    root_cause_service="payment-service",
    root_cause_keywords=["memory_leak", "leak", "webhook", "oom", "heap", "response_object", "unreleased", "gc_unable"],
    correct_remediations=[
        "fix_webhook_handler_memory_leak",
        "increase_memory_limit",
    ],
    alternative_remediations={
        "restart_payment_service": 0.15,
        "reduce_webhook_batch_size": 0.35,
        "add_response_object_cleanup": 0.70,
        "scale_notification_consumers": 0.10,
        "restart_notification_service": 0.10,
        "fix_memory_leak": 0.70,
        "fix_webhook_handler": 0.70,
        "release_response_objects": 0.70,
        "increase_memory": 0.50,
        "increase_memory_allocation": 0.50,
        "increase_heap_size": 0.50,
        "add_gc_cleanup": 0.40,
        "restart_service": 0.15,
    },
    max_steps=20,
    optimal_steps=10,
    red_herring_services={"analytics-worker", "redis-cache"},
)

register_task(scenario)
