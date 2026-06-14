.PHONY: up down logs seed traffic investigate incident-db

up:
	docker-compose up --build -d

down:
	docker-compose down

logs:
	tail -f sample_app/logs/sample_app.jsonl

seed:
	docker-compose exec sample_app python seed.py

traffic:
	uv run python loadgen/run.py

investigate:
	curl -s -X POST http://localhost:8001/investigate \
		-H "Content-Type: application/json" \
		-d "{\"start\": \"$$(date -u -d '10 minutes ago' +%Y-%m-%dT%H:%M:%SZ)\", \"end\": \"$$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}" | python -m json.tool

incident-db:
	python faults/db_down.py
