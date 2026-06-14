"""Inject a postgres_down fault by stopping the Postgres container."""

import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

CONTAINER = "incident-copilot-postgres-1"
FAULT_DURATION_SECONDS = 60
INCIDENT_FILE = Path("faults/last_incident.json")


def _run_docker(args: list[str]) -> None:
    try:
        subprocess.run(
            ["docker", *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        print("docker not found — is Docker installed and on PATH?", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as exc:
        print(exc.stderr or exc.stdout or str(exc), file=sys.stderr)
        sys.exit(1)


def main() -> None:
    incident_start = datetime.now(UTC)
    print(f"💥 Injecting fault: stopping Postgres at {incident_start.isoformat()}")

    _run_docker(["stop", CONTAINER])

    for remaining in range(FAULT_DURATION_SECONDS, 0, -10):
        print(f"⏳ Postgres down... {remaining}s remaining")
        time.sleep(10)

    _run_docker(["start", CONTAINER])

    restore_time = datetime.now(UTC)
    print(f"✅ Postgres restored at {restore_time.isoformat()}")
    print("🔄 Waiting for Postgres to be ready...")
    time.sleep(5)

    INCIDENT_FILE.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "start": incident_start.isoformat(),
        "end": restore_time.isoformat(),
        "duration_seconds": FAULT_DURATION_SECONDS,
        "fault_type": "postgres_down",
        "container": CONTAINER,
    }
    INCIDENT_FILE.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

    print("📝 Incident recorded to faults/last_incident.json")
    print(f"🔍 Investigate window: {record['start']} to {record['end']}")


if __name__ == "__main__":
    main()
