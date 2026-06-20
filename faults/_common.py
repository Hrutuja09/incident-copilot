"""Shared helpers for in-app fault injection scripts."""

import json
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

SAMPLE_APP_URL = "http://localhost:8000"
FAULT_DURATION_SECONDS = 60
INCIDENT_FILE = Path("faults/last_incident.json")


def activate_fault(
    fault_type: str, duration_seconds: int = FAULT_DURATION_SECONDS
) -> None:
    payload = json.dumps({"duration_seconds": duration_seconds}).encode()
    request = urllib.request.Request(
        f"{SAMPLE_APP_URL}/admin/faults/{fault_type}",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            if response.status != 200:
                raise RuntimeError(f"unexpected status {response.status}")
    except urllib.error.URLError as exc:
        print(f"failed to activate fault: {exc}", file=sys.stderr)
        sys.exit(1)


def inject_fault(fault_type: str, label: str) -> None:
    incident_start = datetime.now(UTC)
    print(f"Injecting fault: {label} at {incident_start.isoformat()}")

    activate_fault(fault_type)

    for remaining in range(FAULT_DURATION_SECONDS, 0, -10):
        print(f"Fault active... {remaining}s remaining")
        time.sleep(10)

    restore_time = datetime.now(UTC)
    print(f"Fault window ended at {restore_time.isoformat()}")

    INCIDENT_FILE.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "start": incident_start.isoformat(),
        "end": restore_time.isoformat(),
        "duration_seconds": FAULT_DURATION_SECONDS,
        "fault_type": fault_type,
    }
    INCIDENT_FILE.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

    print("Incident recorded to faults/last_incident.json")
    print(f"Investigate window: {record['start']} to {record['end']}")
