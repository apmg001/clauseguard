.PHONY: install dev test lint run demo

install:
	pip install -e .

dev:
	pip install -e ".[dev,ingestion,matching]"

test:
	pytest -q

lint:
	ruff check src tests

run:
	uvicorn clauseguard.api.app:app --reload

demo:
	python scripts/run_demo.py
