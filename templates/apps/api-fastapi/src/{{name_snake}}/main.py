"""The app: routes, middleware and the store it uses."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response

from {{name_snake}} import items
from {{name_snake}}.store import MemoryStore

log = logging.getLogger("{{name_snake}}")

app = FastAPI(title="{{title}}", description="{{description}}")
app.state.store = MemoryStore()  # tests replace it with a fresh one


@app.middleware("http")
async def log_requests(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    start = time.perf_counter()
    response = await call_next(request)
    ms = (time.perf_counter() - start) * 1000
    log.info("%s %s -> %s in %.1f ms", request.method, request.url.path, response.status_code, ms)
    return response


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(items.router)
