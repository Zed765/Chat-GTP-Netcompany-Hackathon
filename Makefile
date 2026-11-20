.DEFAULT_GOAL := help
COMPOSE := docker compose
TEST_COMPOSE := docker compose -f docker-compose.test.yml
EVAL_NAME ?= $(shell date -u +%Y%m%dT%H%M%SZ)

.PHONY: help up down reset logs smoke acceptance sample-log eval data data-rewrite contracts lint format typecheck test test-deps web-check check

help: ## List the targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

up: ## Build and start everything, then wait until it is healthy and seeded
	$(COMPOSE) up --build -d
	$(COMPOSE) up -d --wait web
	$(COMPOSE) wait seeder

down: ## Stop the stack, keeping its data
	$(COMPOSE) down

reset: ## Stop the stack and delete its data, for a first-boot run
	$(COMPOSE) down --volumes

logs: ## Follow the logs
	$(COMPOSE) logs -f

smoke: ## End-to-end checks against the running stack
	$(COMPOSE) exec -T gateway python -m scripts.smoke

acceptance: ## Checks for the rest of the brief: discovery, policy, protected data, privacy
	$(COMPOSE) exec -T gateway python -m scripts.acceptance
	@! $(COMPOSE) logs --no-color 2>/dev/null | grep -q "GR19 9808 2741" \
		|| (echo "FAIL a value from a prompt is in the container logs" && exit 1)
	@echo "ok   no prompt value in the container logs"

sample-log: ## Write a small proxy log with today's timestamps into inbox/
	python3 -m scripts.sample_log

eval: ## Run the evaluation and copy the results file into eval/results
	$(COMPOSE) exec -T gateway python -m eval.runner --out /tmp/eval-results --name $(EVAL_NAME)
	$(COMPOSE) exec -T gateway cat /tmp/eval-results/$(EVAL_NAME).json > eval/results/$(EVAL_NAME).json

data: ## Regenerate the exemplars, demo data and evaluation sets (offline, deterministic)
	uv run python -m seeder.generate

data-rewrite: ## The same, with the offline model rewriting the prose (needs OPENAI_API_KEY)
	uv run python -m seeder.generate --rewrite

contracts: ## Export the OpenAPI contracts the web app is built against
	uv run python -m scripts.export_openapi

lint: ## Lint Python and check formatting
	uv run ruff check .
	uv run ruff format --check .

format: ## Format Python
	uv run ruff check --fix .
	uv run ruff format .

typecheck: ## Type-check Python
	uv run mypy gateway agent mcp_servers mock_upstream seeder eval scripts

test-deps: ## Start the Postgres and Redis the integration tests need
	$(TEST_COMPOSE) up -d --wait

test: ## Run the Python tests
	uv run pytest

web-check: ## Lint, type-check, test and build the web app
	cd web && npm ci && npm run check

check: lint typecheck test web-check ## Everything CI runs
