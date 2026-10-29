#!/bin/sh
# Retries the startup migration a bounded number of times with backoff (e.g. Postgres not reachable yet, or a
# transient network blip), instead of exiting and letting `restart: unless-stopped` crash-loop forever. After the
# last attempt it sleeps instead of exiting, so the container shows as running-but-unhealthy (the healthcheck has
# nothing to reach) with one clear error in `docker logs`, rather than hundreds of restart attempts burying it.
set -eu

attempt=1
max_attempts=10
delay=2

until alembic upgrade head; do
    if [ "$attempt" -ge "$max_attempts" ]; then
        echo "FATAL: database migrations failed after $max_attempts attempts." >&2
        echo "The API will not start. Check Postgres connectivity (DATABASE_URL, the docker network), then" >&2
        echo "restart this container (docker compose restart api) once it's fixed." >&2
        exec sleep infinity
    fi
    echo "Database not ready (attempt $attempt/$max_attempts); retrying in ${delay}s..." >&2
    sleep "$delay"
    attempt=$((attempt + 1))
    delay=$((delay * 2))
    [ "$delay" -gt 30 ] && delay=30
done

exec uvicorn codewright_api.main:app --host 0.0.0.0 --port 8000 --proxy-headers
