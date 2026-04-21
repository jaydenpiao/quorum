.PHONY: dev test lint demo reset

dev:
	uvicorn apps.api.app.main:app --reload --port 8080

test:
	pytest -q

lint:
	ruff check .

demo:
	python -m apps.api.app.demo_seed

reset:
	rm -f data/events.jsonl data/state_snapshot.json
