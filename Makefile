# Convenience targets. CI (.github/workflows/ci.yml) runs the same checks.
PNPM ?= corepack pnpm
WEB := apps/web

.PHONY: up down logs check check-api check-web test-db

up:            ## Build and start MonoShift (http://localhost:3000)
	docker compose up -d --build --wait

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

check: check-api check-web   ## Everything CI runs, locally

check-api:
	uv sync --all-packages --locked
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy
	uv run pytest

check-web:
	cd $(WEB) && $(PNPM) install --frozen-lockfile && $(PNPM) lint && $(PNPM) typecheck && \
		$(PNPM) format:check && $(PNPM) test && $(PNPM) build

test-db:       ## Create the throwaway test database in the compose Postgres (once)
	docker compose exec -T postgres createdb -U $${POSTGRES_USER:-monoshift} monoshift_test || true
