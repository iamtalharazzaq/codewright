# Convenience targets. Everything runs in Docker; the host only needs Docker Compose.
PNPM ?= corepack pnpm
WEB := apps/web
CHECKS := docker compose --profile checks

.PHONY: up down logs check check-api check-web check-host check-sandbox check-sandbox-host sandbox-images eval-scoreboard eval-nightly

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

check-sandbox-host: ## Preview-port tests (Phase 7 replay): the checks image on the host network, since previews publish on 127.0.0.1 only
	$(CHECKS) build api-checks
	docker run --rm --network host -e SANDBOX_TESTS=1 -e SANDBOX_HOST_LOOPBACK=1 -e SANDBOX_TEST_WORKSPACES=/app/workspaces \
		-e SANDBOX_URL=http://$$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' codewright-sandbox-runner-1):8200 \
		-v codewright_workspaces:/app/workspaces codewright-api-checks:dev pytest -m sandbox agent/tests/playbooks/test_replay_sandbox.py -v

check-web:     ## ESLint, tsc, Prettier and Vitest
	$(CHECKS) build web-checks
	$(CHECKS) run --rm --no-deps web-checks

check-host:    ## The same checks on the host (needs uv and pnpm; DB tests need TEST_DATABASE_URL or SKIP_DB_TESTS=1)
	uv sync --all-packages --locked
	uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
	cd $(WEB) && $(PNPM) install --frozen-lockfile && $(PNPM) lint && $(PNPM) typecheck && \
		$(PNPM) format:check && $(PNPM) test

eval-scoreboard:  ## The newest result of each eval suite as one table (no model needed)
	docker compose --profile checks run --rm --no-deps api-checks python3 -m evals.scoreboard

eval-nightly:  ## (export LLM_REMOTE_GPU_URL first) The live suites in turn (needs the stack up and the model reachable), then the scoreboard
	$(CHECKS) run --rm -v $(CURDIR)/evals:/app/evals -e LLM_URL=$${LLM_REMOTE_GPU_URL} api-checks sh -c 'python3 -m evals.router --url $$LLM_URL'
	python3 -m evals.examples
	python3 -m evals.new_app
	python3 -m evals.write_code
	$(MAKE) eval-scoreboard
