.PHONY: help up down logs build seed migrate revision test lint typecheck check demo fmt venv

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

demo: ## Run the BE-0 curl walkthrough
	./scripts/demo_be0.sh

venv: ## Create the host venv used by test/lint/typecheck
	uv venv --python 3.12 .venv
	uv pip install --python .venv/bin/python -e ".[dev]"
