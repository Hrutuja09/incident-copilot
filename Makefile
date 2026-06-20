.PHONY: up down logs seed traffic investigate incident-db incident-memory incident-timeout incident-bad-deploy demo capture

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

incident-memory:
	python faults/memory_exhaustion.py

incident-timeout:
	python faults/dependency_timeout.py

incident-bad-deploy:
	python faults/bad_deploy.py

demo:
	bash scripts/demo.sh

capture:
	python scripts/capture_scenario.py --all
