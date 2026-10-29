# 0034. Codewright's Docker bridge network stopped forwarding traffic (2026-10-29)

- **Status:** resolved (network recreated); root cause not fully pinned down
- **Date:** 2026-10-29

## What happened

Partway through a session, `codewright-api-1` could no longer reach `postgres`, `sandbox-runner` or `web` over
the `codewright_default` bridge (172.22.0.0/16) — every TCP connect timed out, from both the long-running `api`
container and fresh `docker compose run --rm` containers. `postgres` itself was healthy (answered `psql` from
inside its own container, `pg_isready` passed) and its container's IP/network membership looked correct in
`docker network inspect`. Because `api`'s startup runs `alembic upgrade head` before serving, and that now timed
out every attempt, `restart: unless-stopped` kept recreating the container in a tight loop for over an hour — the
entire live app (chat, runs, graph, every playbook) was down the whole time; only `web`'s static Next.js shell
kept responding, since it doesn't touch Postgres at startup.

## Investigation

- No subnet overlap between `codewright_default` (172.22.0.0/16) and any other Docker network on the host
  (bridge, `dev_default`, `heart-agent_default`, `hiring-compass-internal`, `infra_default` — all distinct
  `/16`s).
- No VPN/Tailscale/ngrok/WireGuard process running on this host (the remote GPU's ngrok tunnel runs on the
  *Windows* GPU machine, not here) — ruled out a VPN route stealing part of the subnet.
- The host's `br-fab15004052e` (= `codewright_default`) interface was up with the right address; `ip_forward` and
  `bridge-nf-call-iptables` were both `1` (correct defaults for inter-container forwarding).
- Could not inspect the actual `iptables`/`nftables` FORWARD rules (no sudo in this environment), so the specific
  stale rule, if that's what it was, was never directly observed.
- `docker compose logs postgres` showed an unplanned restart/recovery (`database system was interrupted`) a few
  minutes before the symptom was first noticed, with nothing in this session's own command history that should
  have restarted it.

No definitive single cause was found. The leading theory, consistent with the evidence (no subnet/VPN clash,
host-level forwarding settings correct, but inter-container traffic on this one bridge specifically broken): the
bridge's Docker-managed iptables rules went stale, plausibly from the heavy container churn this session put on
that one network (many `docker compose run --rm` invocations in quick succession, plus a dangling-image prune)
without a Docker daemon restart to reconcile them. This is a known class of Docker networking issue, not unique
to Codewright.

## Fix

1. `docker compose down` (no `-v`) then `docker compose up -d --build --wait`, scoped to Codewright's own compose
   project — recreates the bridge network and every container's network attachment from scratch. Confirmed
   working afterward: inter-container TCP to `postgres`/`sandbox-runner`/`web` all succeed, `/api/health/ready`
   reports every check `ok`, a real chat message round-tripped through the remote GPU, and a `write_code` run
   reached the real sandbox, passed 12 generated tests, and stopped cleanly at its approval gate.
2. Postgres data was never at risk (named volume, not recreated by `down` without `-v`); a `pg_dumpall` backup was
   still taken first as a precaution (`backups/codewright-pre-recreate-*.sql`, gitignored).
3. **Hardened `api`'s own startup** so this class of problem degrades more visibly next time: `apps/api/entrypoint.sh`
   retries `alembic upgrade head` up to 10 times with backoff (2s, doubling, capped at 30s) instead of exiting
   immediately. If every attempt fails, it logs one clear fatal message and sleeps instead of exiting — the
   container shows as running-but-unhealthy (and the real error sits once in the logs) rather than Docker
   silently crash-looping it forever. `restart: unless-stopped` is left as-is (recovers on its own once the
   network issue is actually fixed and the container is restarted), rather than switching to a bounded
   `on-failure:N`, which would require a manual `docker compose up` to come back even after the real fix.

## Open

If this recurs, the next step (needs host root) is reading the actual `iptables -L FORWARD -n -v` /
`iptables -t nat -L -n -v` state on the affected bridge before recreating it, to confirm the stale-rule theory
instead of inferring it from the ruled-out alternatives above.
