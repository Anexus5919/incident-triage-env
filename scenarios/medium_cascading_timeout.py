"""
Medium scenario: Cascading service timeouts caused by a slow database query.

A missing index on the ``orders`` table causes full table scans on
postgres-primary.  The connection pool backs up through order-service ->
api-gateway -> web-frontend.  One red herring: redis-cache shows a minor
eviction spike that is unrelated.

Optimal path (7 steps):
  check_logs web-frontend -> check_dependencies web-frontend ->
  check_logs api-gateway  -> check_logs order-service ->
  check_logs postgres-primary -> diagnose -> remediate (x2)
"""

from .registry import Scenario, ServiceInfo, register_task

scenario = Scenario(
    task_id="medium_cascading_timeout",
    difficulty="medium",
    title="Cascading Service Timeouts",
    description=(
        "INCIDENT: Multiple alerts are firing simultaneously across the web "
        "frontend, API gateway, and backend services. End-users are seeing slow "
        "page loads and intermittent 504 Gateway Timeout errors. Three services "
        "appear degraded. Trace the dependency chain, identify the root cause, "
        "and apply remediations to restore service."
    ),
    services={
        "web-frontend": ServiceInfo(
            name="web-frontend",
            status="degraded",
            dependencies=["api-gateway"],
        ),
        "api-gateway": ServiceInfo(
            name="api-gateway",
            status="degraded",
            dependencies=["order-service", "auth-service"],
        ),
        "order-service": ServiceInfo(
            name="order-service",
            status="degraded",
            dependencies=["postgres-primary", "redis-cache"],
        ),
        "postgres-primary": ServiceInfo(
            name="postgres-primary",
            status="degraded",
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
            "service": "web-frontend",
            "message": "P99 latency > 30 s, error rate 22%",
            "timestamp": "09:15",
        },
        {
            "severity": "critical",
            "service": "api-gateway",
            "message": "Upstream timeout: order-service (p99 > 30 s)",
            "timestamp": "09:14",
        },
        {
            "severity": "warning",
            "service": "order-service",
            "message": "DB connection pool exhausted (50/50)",
            "timestamp": "09:12",
        },
        {
            "severity": "warning",
            "service": "postgres-primary",
            "message": "Active connections: 498/500, CPU 92%",
            "timestamp": "09:11",
        },
        {
            "severity": "info",
            "service": "redis-cache",
            "message": "Eviction rate slightly elevated (3/min)",
            "timestamp": "09:14",
        },
    ],
    log_data={
        "web-frontend": (
            "[09:14:01] ERROR Gateway timeout: POST /checkout -> 504 (30002 ms)\n"
            "[09:14:15] ERROR Gateway timeout: GET /orders -> 504 (30001 ms)\n"
            "[09:14:30] WARN  Retry queue depth: 245 requests backed up\n"
            "[09:15:00] ERROR Circuit breaker OPEN for api-gateway (failure rate 22%)\n"
            "[09:15:05] WARN  Serving stale cached product page (age 12 min)\n"
        ),
        "api-gateway": (
            "[09:13:30] WARN  Upstream timeout: order-service POST /api/orders (30 s)\n"
            "[09:13:45] ERROR Connection refused by order-service: pool exhausted\n"
            "[09:14:00] WARN  Health check FAILED for order-service (attempt 3/3)\n"
            "[09:14:10] ERROR 47 requests queued waiting for order-service connection\n"
            "[09:14:20] INFO  auth-service responding normally (p99 15 ms)\n"
        ),
        "order-service": (
            "[09:11:00] WARN  DB connection pool: 48/50 active\n"
            "[09:11:30] WARN  DB connection pool: 50/50 active — new requests will block\n"
            "[09:12:00] ERROR Cannot acquire DB connection within 5000 ms timeout\n"
            "[09:12:15] ERROR Slow query: SELECT * FROM orders WHERE status='pending' "
            "AND created_at > now()-interval '7 days' — 28.5 s (seq scan, 2.1 M rows)\n"
            "[09:12:30] WARN  15 threads blocked waiting for DB connection\n"
            "[09:12:45] ERROR Query cancelled after 30 s timeout\n"
        ),
        "postgres-primary": (
            "[09:10:00] LOG  slow query: 28542 ms — SELECT * FROM orders "
            "WHERE status='pending' AND created_at > '2026-03-31' "
            "(Seq Scan on orders, rows=2100000)\n"
            "[09:10:30] LOG  active connections: 485/500\n"
            "[09:11:00] LOG  slow query: 31205 ms — same query pattern repeated\n"
            "[09:11:30] WARNING connection slots remaining: 15\n"
            "[09:12:00] LOG  active connections: 498/500\n"
            "[09:12:00] LOG  autovacuum: table 'orders' has 2.1 M dead tuples\n"
            "[09:12:15] LOG  HINT: consider adding index on (status, created_at)\n"
        ),
        "redis-cache": (
            "[09:13:00] # Clients connected: 45\n"
            "[09:14:00] # Evicted keys: 12 (maxmemory policy: allkeys-lru)\n"
            "[09:14:30] # Memory: 1.8 GB / 2 GB — near limit but stable\n"
            "[09:14:45] # Hit rate: 89% (slightly below 95% target)\n"
        ),
    },
    metrics_data={
        "web-frontend": {
            "cpu_pct": 35.0,
            "memory_pct": 50.0,
            "disk_usage_pct": 25.0,
            "error_rate_pct": 22.0,
            "requests_per_sec": 200,
            "p99_latency_ms": 30000,
        },
        "api-gateway": {
            "cpu_pct": 40.0,
            "memory_pct": 55.0,
            "disk_usage_pct": 20.0,
            "error_rate_pct": 18.0,
            "requests_per_sec": 180,
            "p99_latency_ms": 30000,
            "upstream_timeout_count": 47,
        },
        "order-service": {
            "cpu_pct": 85.0,
            "memory_pct": 78.0,
            "disk_usage_pct": 30.0,
            "error_rate_pct": 15.0,
            "db_pool_active": 50,
            "db_pool_max": 50,
            "blocked_threads": 15,
        },
        "postgres-primary": {
            "cpu_pct": 92.0,
            "memory_pct": 88.0,
            "disk_usage_pct": 55.0,
            "error_rate_pct": 2.0,
            "active_connections": 498,
            "max_connections": 500,
            "slow_queries_per_min": 8,
            "avg_query_time_ms": 15000,
            "dead_tuples": 2100000,
        },
        "redis-cache": {
            "cpu_pct": 15.0,
            "memory_pct": 90.0,
            "disk_usage_pct": 10.0,
            "error_rate_pct": 0.1,
            "hit_rate_pct": 89.0,
            "evictions_per_min": 3,
            "connected_clients": 45,
        },
    },
    dependency_data={
        "web-frontend": (
            "Upstream dependencies:\n"
            "  - api-gateway (all API calls via HTTP, port 443)\n"
            "Downstream consumers:\n"
            "  - CDN / end-user browsers"
        ),
        "api-gateway": (
            "Upstream dependencies:\n"
            "  - order-service (order CRUD, port 8081)\n"
            "  - auth-service (JWT validation, port 8082) — currently healthy\n"
            "Downstream consumers:\n"
            "  - web-frontend"
        ),
        "order-service": (
            "Upstream dependencies:\n"
            "  - postgres-primary (data store, port 5432, pool size 50)\n"
            "  - redis-cache (order-level caching, port 6379)\n"
            "Downstream consumers:\n"
            "  - api-gateway\n"
            "  - notification-worker (async, via RabbitMQ)"
        ),
        "postgres-primary": (
            "Upstream dependencies: none\n"
            "Downstream consumers:\n"
            "  - order-service (read/write, pool 50)\n"
            "  - analytics-worker (read replica, async)\n"
            "NOTE: Table 'orders' has 2.1 M rows, no index on (status, created_at)"
        ),
        "redis-cache": (
            "Upstream dependencies: none\n"
            "Downstream consumers:\n"
            "  - order-service (cache), web-frontend (sessions)\n"
            "NOTE: Memory near maxmemory — evictions occurring but hit-rate OK"
        ),
    },
    root_cause="slow_query_missing_index",
    root_cause_service="postgres-primary",
    root_cause_keywords=["slow_query", "missing_index", "index", "table_scan", "seq_scan", "full_scan", "query_timeout", "connection_pool", "connection_exhaust"],
    correct_remediations=[
        "add_index_orders_status_created",
        "increase_connection_pool",
    ],
    alternative_remediations={
        "restart_order_service": 0.15,
        "kill_slow_queries": 0.30,
        "vacuum_orders_table": 0.25,
        "add_read_replica": 0.20,
        "add_index": 0.70,
        "create_index": 0.70,
        "optimize_query": 0.40,
        "optimize_slow_queries": 0.40,
        "increase_connections": 0.50,
        "increase_max_connections": 0.50,
        "increase_pool_size": 0.50,
        "add_database_index": 0.70,
    },
    max_steps=15,
    optimal_steps=7,
    red_herring_services={"redis-cache"},
)

register_task(scenario)
