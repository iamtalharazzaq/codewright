"""Scripted build for the live graph (CODEWRIGHT.md Phase 4 acceptance): create an empty project, then copy a
codebase into it one file at a time, asking for a graph update after each file, like a builder agent would.

    docker compose exec api python -m codewright_api.demo_build /app/workspaces/<project>/source --name live-goshop

Open the new project's Graph explorer (the URL is printed) and watch the graph grow.
"""

from __future__ import annotations

import argparse
import shutil
import time
from pathlib import Path

import httpx

from agent.knowledge_graph import module_of
from agent.tools.code_search import CODE_SUFFIXES
from codewright_api.settings import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", type=Path, help="folder to copy from")
    parser.add_argument("--name", default="live build")
    parser.add_argument("--api", default="http://localhost:8000/api")
    parser.add_argument("--delay", type=float, default=0.3, help="seconds between files")
    parser.add_argument("--limit", type=int, default=0, help="stop after this many files (0 = all)")
    args = parser.parse_args()

    files = sorted(
        p
        for p in args.source.rglob("*")
        if p.is_file() and p.suffix.lower() in CODE_SUFFIXES and module_of(str(p.relative_to(args.source))) is not None
    )
    if args.limit:
        files = files[: args.limit]
    with httpx.Client(base_url=args.api, timeout=30) as api:
        project = api.post("/projects", data={"kind": "empty", "name": args.name}).raise_for_status().json()
        print(f"Project {project['id']}: open /projects/{project['id']}/graph")
        work = get_settings().workspaces_dir / project["id"] / "work"
        for i, src in enumerate(files, 1):
            rel = src.relative_to(args.source)
            dest = work / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)
            api.post(f"/projects/{project['id']}/graph", json={"paths": [str(rel)], "reason": "build"})
            print(f"[{i}/{len(files)}] {rel}")
            time.sleep(args.delay)


if __name__ == "__main__":
    main()
