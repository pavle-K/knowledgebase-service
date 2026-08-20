.PHONY: test test-unit lint

VENV := .venv/bin

test:
	$(VENV)/pytest --cov=src --cov-report=term-missing

test-unit:
	$(VENV)/pytest tests/unit

lint:
	$(VENV)/ruff check .
	$(VENV)/ruff format --check .
	$(VENV)/mypy src/
