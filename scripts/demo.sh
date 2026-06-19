#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "🚀 AI Incident Copilot — Live Demo"
echo "===================================="
echo "Starting demo at $(date -u)"

check_health() {
  curl -sf -o /dev/null "$1"
}

if ! check_health "http://localhost:8000/health" || ! check_health "http://localhost:8001/health"; then
  echo "❌ Services not running. Run 'make up' first."
  exit 1
fi

python loadgen/run.py &
TRAFFIC_PID=$!
echo "✅ Traffic generator started (PID $TRAFFIC_PID)"

for remaining in 120 90 60 30; do
  echo "⏳ Establishing baseline... ${remaining}s remaining"
  sleep 30
done
echo "✅ Baseline established"

echo "💥 Injecting fault: stopping Postgres..."
python faults/db_down.py

sleep 15
echo "✅ System recovered. Running diagnosis..."

INVESTIGATE_PAYLOAD=$(python3 -c "
import json
with open('faults/last_incident.json') as f:
    incident = json.load(f)
print(json.dumps({
    'start': incident['start'],
    'end': incident['end'],
    'lookback_seconds': 300,
}))
")

RESPONSE=$(curl -s -X POST http://localhost:8001/investigate \
  -H "Content-Type: application/json" \
  -d "$INVESTIGATE_PAYLOAD")

echo "===================================="
echo "🔍 RCA REPORT"
echo "===================================="
echo "$RESPONSE" | python -m json.tool

kill "$TRAFFIC_PID" 2>/dev/null || true
echo "✅ Traffic generator stopped"
echo "Demo complete."
