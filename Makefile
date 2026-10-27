# Convenience targets. Everything runs in Docker; the host only needs Docker Compose.
PNPM ?= corepack pnpm
WEB := apps/web
CHECKS := docker compose --profile checks

.PHONY: up down logs check check-api check-web check-host

up:            ## Build and start Codewright (http://localhost:3000)
	docker compose up -d --build --wait

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

check: check-api check-web   ## Every lint/type/test check, in containers

check-api:     ## ruff, mypy and pytest (incl. the Postgres tests, on a throwaway codewright_test database)
	$(CHECKS) build api-checks
	$(CHECKS) run --rm api-checks

check-web:     ## ESLint, tsc, Prettier and Vitest
	$(CHECKS) build web-checks
	$(CHECKS) run --rm --no-deps web-checks

check-host:    ## The same checks on the host (needs uv and pnpm; DB tests need TEST_DATABASE_URL or SKIP_DB_TESTS=1)
	uv sync --all-packages --locked
	uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
	cd $(WEB) && $(PNPM) install --frozen-lockfile && $(PNPM) lint && $(PNPM) typecheck && \
		$(PNPM) format:check && $(PNPM) test
