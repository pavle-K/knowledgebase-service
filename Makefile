-include .env
export

.PHONY: test test-unit lint db-up migrate sync-local

VENV := .venv/bin

test:
	$(VENV)/pytest --cov=src --cov-report=term-missing

test-unit:
	$(VENV)/pytest tests/unit

lint:
	$(VENV)/ruff check .
	$(VENV)/ruff format --check .
	$(VENV)/mypy src/

db-up:
	docker compose up -d postgres

migrate:
	$(VENV)/python scripts/migrate.py

sync-local:
	$(VENV)/python scripts/sync_github.py
