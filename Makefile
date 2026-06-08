.PHONY: up down logs seed traffic

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
