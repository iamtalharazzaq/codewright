from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request

from codewright_api.runs import RunManager


def get_manager(request: Request) -> RunManager:
    manager: RunManager | None = getattr(request.app.state, "run_manager", None)
    if manager is None:
        raise HTTPException(503, "The run manager is not available (is the database reachable?).")
    return manager


ManagerDep = Annotated[RunManager, Depends(get_manager)]
