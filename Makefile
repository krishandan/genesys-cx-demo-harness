.PHONY: help up down logs build seed migrate revision test lint typecheck check demo demo-be1 demo-be2 demo-be3 demo-be4 contracts fmt venv

ENV_FILE := .env
POSTGRES_DATA_PATH ?= ./.data/postgres

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

$(ENV_FILE):
	@test -f $(ENV_FILE) || (cp .env.example $(ENV_FILE) && echo "created .env from .env.example")

datadir:
	@mkdir -p $(POSTGRES_DATA_PATH)

up: $(ENV_FILE) datadir ## Build and start api + db
	docker compose up -d --build
	@echo "api → http://localhost:8000/health   docs → http://localhost:8000/docs"

down: ## Stop the stack (data survives)
	docker compose down

build: $(ENV_FILE) ## Rebuild images
	docker compose build

logs: ## Tail api logs
	docker compose logs -f api

migrate: ## Apply migrations inside the api container
	docker compose exec api alembic upgrade head

revision: ## Autogenerate a migration: make revision m="message"
	docker compose exec api alembic revision --autogenerate -m "$(m)"

seed: ## Seed the Northwind pack (idempotent)
	docker compose exec api python -m app.seed --tenant northwind

test: ## Run pytest on the host venv
	.venv/bin/pytest

lint: ## ruff
	.venv/bin/ruff check .

fmt: ## ruff --fix
	.venv/bin/ruff check . --fix

typecheck: ## mypy
	.venv/bin/mypy app

check: lint typecheck test ## The phase gate's static+test leg

contracts: ## Regenerate the Genesys data-action contracts into contracts/
	.venv/bin/python -m app.gx.contracts

demo: ## Run the BE-0 curl walkthrough
	./scripts/demo_be0.sh

demo-be1: ## Run the BE-1 gx walkthrough
	./scripts/demo_be1.sh

demo-be2: ## Run the BE-2 WiFi self-healing walkthrough
	./scripts/demo_be2.sh

demo-be3: ## Run the BE-3 scenario engine walkthrough
	./scripts/demo_be3.sh

demo-be4: ## Run the BE-4 events + CSAT + telemetry walkthrough
	./scripts/demo_be4.sh

demo-be5: ## Run the BE-5 Demo-1 backend arc
	./scripts/demo_be5.sh

venv: ## Create the host venv used by test/lint/typecheck
	uv venv --python 3.12 .venv
	uv pip install --python .venv/bin/python -e ".[dev]"
