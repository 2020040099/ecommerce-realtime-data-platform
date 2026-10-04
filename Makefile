SHELL := /bin/bash
.DEFAULT_GOAL := help
.PHONY: help install lint format test check up down ps logs psql db-reset

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

# ---------- Python ----------
install: ## Install all dependencies exactly as pinned in uv.lock
	uv sync

lint: ## Check code style without changing files
	uv run ruff check .
	uv run ruff format --check .

format: ## Auto-fix lint issues and reformat code
	uv run ruff check --fix .
	uv run ruff format .

test: ## Run the test suite
	uv run pytest

check: lint test ## Run everything CI runs: lint + tests

# ---------- Docker ----------
up: ## Start all services in the background
	docker compose up -d

down: ## Stop and remove containers (data volumes are kept)
	docker compose down

ps: ## Show service status
	docker compose ps

logs: ## Follow logs from all services (Ctrl+C to exit)
	docker compose logs -f

psql: ## Open an interactive psql shell on the analytics database
	docker compose exec postgres sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'

db-reset: ## DANGER: remove containers AND all local database data
	@read -p "This deletes ALL local database data. Type 'yes' to continue: " ans && [ "$$ans" = "yes" ]
	docker compose down -v
