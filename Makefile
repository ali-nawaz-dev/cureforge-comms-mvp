# CureForge Comms MVP — Developer shortcuts
# Usage: make <target>

.PHONY: help install lint test test-all dashboard webhook migrate import-contacts

help:          ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*##' Makefile | awk 'BEGIN{FS=":.*##"}{printf "  \033[36m%-22s\033[0m %s\n",$$1,$$2}'

install:       ## Install all dependencies (editable)
	pip install -e ".[dev,test]"

lint:          ## Run ruff linter
	python -m ruff check .

lint-fix:      ## Auto-fix ruff lint errors
	python -m ruff check . --fix

test:          ## Run unit tests (no external services needed)
	python -m pytest tests/ -q

test-cov:      ## Run unit tests with coverage on packages/ and services/
	python -m pytest tests/ -q --cov=packages --cov=services --cov-report=term-missing

test-verbose:  ## Run unit tests with full output
	python -m pytest tests/ -v

test-all:      ## Run integration tests via Docker Compose (needs Docker)
	docker compose -f docker-compose.test.yml up --build --abort-on-container-exit

dashboard:     ## Start the Streamlit dashboard locally
	streamlit run apps/dashboard/app.py --server.port=8501

webhook:       ## Start the FastAPI inbound webhook server locally
	uvicorn services.outreach.webhook:app --host 0.0.0.0 --port 8000 --reload

docker-up:     ## Start full stack (Postgres + Redis + dashboard) via Docker Compose
	docker compose up --build

docker-down:   ## Tear down Docker Compose stack
	docker compose down -v

migrate:       ## Apply Postgres migrations (needs DATABASE_URL in .env)
	python -c "from packages.db.connection import run_migrations; run_migrations()"

import-contacts: ## Import contacts from CSV/JSON (usage: make import-contacts FILE=path/to/file.csv)
	python -m services.matching.cli_import --file $(FILE) --dry-run

publish-milestone: ## Publish an internal milestone (usage: make publish-milestone TITLE="..." BODY="...")
	python -m services.matching.milestones --title "$(TITLE)" --body "$(BODY)"

redis-e2e:       ## Live Redis bus walkthrough (needs Redis on REDIS_URL)
	PYTHONPATH=. BUS_BACKEND=redis REDIS_URL=$${REDIS_URL:-redis://localhost:6379/0} python3.11 scripts/redis_bus_e2e.py
