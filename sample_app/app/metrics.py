from prometheus_client import Counter, Gauge, Histogram

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status_code"],
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "endpoint"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5],
)

DB_HEALTHY = Gauge(
    "db_healthy",
    "Database health status (1=healthy, 0=unhealthy)",
)

PROCESS_MEMORY_BYTES = Gauge(
    "process_memory_bytes",
    "Simulated process memory usage in bytes",
)

DOWNSTREAM_REQUEST_DURATION_SECONDS = Histogram(
    "downstream_request_duration_seconds",
    "Downstream dependency call duration in seconds",
    ["dependency"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0],
)

DOWNSTREAM_TIMEOUTS_TOTAL = Counter(
    "downstream_timeouts_total",
    "Total downstream dependency timeouts",
    ["dependency"],
)

APP_DEPLOY_INFO = Gauge(
    "app_deploy_info",
    "Active deploy version (1=current good build, 0=unknown/bad)",
    ["version"],
)
