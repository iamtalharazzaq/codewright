# Convenience targets. Everything runs in Docker; the host only needs Docker Compose.
PNPM ?= corepack pnpm
WEB := apps/web
CHECKS := docker compose --profile checks

.PHONY: up down logs check check-api check-web check-host check-sandbox sandbox-images

up: sandbox-images  ## Build and start Codewright (http://localhost:3000)
	docker compose up -d --build --wait

sandbox-images: ## Build the sandbox images: four toolchains (Python, Go, Node, C++), verification tools, a browser
	for t in python go node cpp tools browser; do docker build -t codewright-sandbox-$$t:dev -f sandbox/images/$$t.Dockerfile sandbox/images || exit 1; done

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

check: check-api check-web   ## Every lint/type/test check, in containers

check-api:     ## ruff, mypy and pytest (incl. the Postgres tests, on a throwaway codewright_test database)
	$(CHECKS) build api-checks
	$(CHECKS) run --rm api-checks

check-sandbox: ## Every template and pack fixture built, tested, linted and run in the real sandbox (needs `make up`)
	$(CHECKS) build api-checks
	$(CHECKS) run --rm -e SANDBOX_TESTS=1 api-checks pytest -m sandbox -v

check-web:     ## ESLint, tsc, Prettier and Vitest
	$(CHECKS) build web-checks
	$(CHECKS) run --rm --no-deps web-checks

check-host:    ## The same checks on the host (needs uv and pnpm; DB tests need TEST_DATABASE_URL or SKIP_DB_TESTS=1)
	uv sync --all-packages --locked
	uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
	cd $(WEB) && $(PNPM) install --frozen-lockfile && $(PNPM) lint && $(PNPM) typecheck && \
		$(PNPM) format:check && $(PNPM) test
