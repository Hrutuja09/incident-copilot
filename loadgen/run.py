"""Simple load generator for sample_app order endpoint."""

import random
import signal
import sys
import time

import httpx

BASE_URL = "http://localhost:8000"
TARGET_RPS = 10.0
JITTER = 0.20
SUMMARY_INTERVAL_S = 30.0
ORDER_ID_MIN = 1
ORDER_ID_MAX = 10

running = True


def _handle_sigint(_signum: int, _frame: object) -> None:
    global running
    running = False


def main() -> None:
    signal.signal(signal.SIGINT, _handle_sigint)

    total_requests = 0
    total_errors = 0
    total_latency_s = 0.0
    window_requests = 0
    window_errors = 0
    window_latency_s = 0.0
    window_start = time.monotonic()
    summary_start = window_start

    print(f"Load generator started — target ~{TARGET_RPS:.0f} rps, Ctrl+C to stop")

    with httpx.Client(timeout=10.0) as client:
        while running:
            order_id = random.randint(ORDER_ID_MIN, ORDER_ID_MAX)
            url = f"{BASE_URL}/order/{order_id}"

            start = time.perf_counter()
            try:
                response = client.get(url)
                response.raise_for_status()
            except httpx.HTTPError:
                window_errors += 1
                total_errors += 1
            else:
                elapsed = time.perf_counter() - start
                window_latency_s += elapsed
                total_latency_s += elapsed
            finally:
                window_requests += 1
                total_requests += 1

            now = time.monotonic()
            if now - summary_start >= SUMMARY_INTERVAL_S:
                avg_latency_ms = (
                    (window_latency_s / (window_requests - window_errors) * 1000)
                    if window_requests > window_errors
                    else 0.0
                )
                print(
                    f"summary: requests={window_requests} errors={window_errors} "
                    f"avg_latency_ms={avg_latency_ms:.1f}"
                )
                window_requests = 0
                window_errors = 0
                window_latency_s = 0.0
                summary_start = now

            interval = (1.0 / TARGET_RPS) * random.uniform(1.0 - JITTER, 1.0 + JITTER)
            time.sleep(interval)

    if total_requests:
        avg_latency_ms = (
            (total_latency_s / (total_requests - total_errors) * 1000)
            if total_requests > total_errors
            else 0.0
        )
        print(
            f"stopped: total_requests={total_requests} total_errors={total_errors} "
            f"avg_latency_ms={avg_latency_ms:.1f}"
        )
    else:
        print("stopped")


if __name__ == "__main__":
    main()
    sys.exit(0)
