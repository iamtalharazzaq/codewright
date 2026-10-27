"""Projects: import from a source into a workspace, scan for secrets, summarize; and delivery (CODEWRIGHT.md 8.1, C7).

Imports run in the background: the project is `importing` until its files are in `workspaces/<id>/` (source/ + work/
git repo), then `ready` (or `failed` with a reason).
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent.tools.secrets import scan_tree
from agent.tools.workspace import Workspace
from codewright_api.db import Project, Run
from codewright_api.gdrive import drive_access_token
from codewright_api.settings import Settings
from connectors.inputs import InputError, clone_github, copy_local, download_drive_zip, extract_zip
from connectors.outputs import DeliveryError, make_zip, to_drive, to_github, to_local

log = logging.getLogger(__name__)

TARGETS = ("local", "zip", "github", "drive")


def workspace(settings: Settings, project_id: uuid.UUID | str) -> Workspace:
    return Workspace(settings.workspaces_dir, str(project_id))


def summary_dict(ws: Workspace) -> dict[str, Any]:
    s = ws.summary()
    return {"files": s.files, "size_bytes": s.size_bytes, "languages": s.languages, "top_level": s.top_level}


class ProjectService:
    def __init__(self, settings: Settings, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.settings = settings
        self.sessions = sessions
        self._tasks: set[asyncio.Task[None]] = set()

    # ── import ───────────────────────────────────────────────────────────────
    async def create(self, name: str, kind: str, ref: str = "", upload: Path | None = None) -> Project:
        async with self.sessions() as session:
            project = Project(
                name=name.strip() or "Untitled project",
                status="importing" if kind != "empty" else "ready",
                source={"kind": kind, "ref": ref},
            )
            session.add(project)
            await session.commit()
            await session.refresh(project)
        if kind == "empty":
            ws = workspace(self.settings, project.id)
            await asyncio.to_thread(ws.create)
            await asyncio.to_thread(ws.init_git)
        else:
            task = asyncio.create_task(self._import(project.id, kind, ref, upload))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        return project

    async def _import(self, project_id: uuid.UUID, kind: str, ref: str, upload: Path | None) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="import-", dir=self.settings.workspaces_dir))
        try:
            tree = await self._fetch(kind, ref, upload, tmp)
            ws = workspace(self.settings, project_id)
            await asyncio.to_thread(ws.import_tree, tree)
            findings = [f.as_dict() for f in await asyncio.to_thread(scan_tree, ws.source)]
            values: dict[str, Any] = {
                "status": "ready",
                "summary": await asyncio.to_thread(summary_dict, ws),
                "secrets": findings,
                "error": None,
            }
        except InputError as exc:
            values = {"status": "failed", "error": str(exc)}
        except Exception as exc:
            log.exception("project import failed")
            values = {"status": "failed", "error": f"Import failed: {exc}"}
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            if upload is not None:
                upload.unlink(missing_ok=True)
        async with self.sessions() as session:
            project = await session.get(Project, project_id)
            if project is not None:
                for k, v in values.items():
                    setattr(project, k, v)
                await session.commit()

    async def _fetch(self, kind: str, ref: str, upload: Path | None, tmp: Path) -> Path:
        if kind == "zip":
            if upload is None:
                raise InputError("No ZIP was uploaded.")
            return await asyncio.to_thread(extract_zip, upload, tmp / "tree")
        if kind == "github":
            token = self.settings.github_token.get_secret_value() if self.settings.github_token else None
            return await asyncio.to_thread(clone_github, ref, tmp / "tree", token)
        if kind == "local":
            return await asyncio.to_thread(copy_local, ref, self.settings.local_source_root, tmp / "tree")
        if kind == "drive":
            archive = await download_drive_zip(
                ref, tmp / "drive.zip", await drive_access_token(self.sessions, self.settings)
            )
            return await asyncio.to_thread(extract_zip, archive, tmp / "tree")
        raise InputError(f"Unknown source {kind!r}.")

    async def delete(self, project_id: uuid.UUID) -> None:
        await asyncio.to_thread(workspace(self.settings, project_id).delete)

    # ── delivery ─────────────────────────────────────────────────────────────
    async def deliver(
        self,
        targets: list[str],
        *,
        project: Project | None = None,
        run: Run | None = None,
        github_repo: str | None = None,
    ) -> list[dict[str, Any]]:
        """Deliver a project's `work/` (its current branch) or a run's workspace. One result per target."""
        if project is not None:
            ws = workspace(self.settings, project.id)
            src, name = ws.work, project.name
        elif run is not None:
            src = self.settings.workspaces_dir / (str(run.project_id) if run.project_id else f"_runs/{run.id}")
            name, ws = f"{run.playbook}-{str(run.id)[:8]}", None
        else:
            raise DeliveryError("Nothing to deliver.")
        if not src.is_dir():
            raise DeliveryError("The files to deliver are gone (was the project deleted?).")

        results: list[dict[str, Any]] = []
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        for target in targets:
            try:
                results.append(
                    {
                        "target": target,
                        "ok": True,
                        **await self._deliver_one(target, src, name, stamp, ws, project, github_repo),
                    }
                )
            except (DeliveryError, InputError, RuntimeError) as exc:
                results.append({"target": target, "ok": False, "error": str(exc)})
        return results

    async def _deliver_one(
        self,
        target: str,
        src: Path,
        name: str,
        stamp: str,
        ws: Workspace | None,
        project: Project | None,
        github_repo: str | None,
    ) -> dict[str, Any]:
        safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in name)[:60] or "codewright"
        if target == "local":
            out = self.settings.output_root
            path = await asyncio.to_thread(to_local, src, [out] if out else [], safe)
            return {"location": f"deliveries/{path.name}", "detail": "Copied into your deliveries folder."}
        if target == "zip":
            archive = self.settings.workspaces_dir / "_deliveries" / f"{safe}-{stamp}.zip"
            await asyncio.to_thread(make_zip, src, archive)
            return {"location": f"/api/deliveries/{archive.name}", "detail": "ZIP ready to download."}
        if target == "drive":
            archive = self.settings.workspaces_dir / "_deliveries" / f"{safe}-{stamp}.zip"
            await asyncio.to_thread(make_zip, src, archive)
            token = await drive_access_token(self.sessions, self.settings)
            link = await to_drive(archive, token, archive.name)
            return {"location": link, "detail": "Uploaded to Google Drive."}
        if target == "github":
            repo = github_repo or (
                project.source.get("ref") if project and project.source.get("kind") == "github" else None
            )
            if not repo:
                raise DeliveryError("Which GitHub repository? Enter its URL.")
            if ws is None:
                raise DeliveryError(
                    "Only projects can be delivered to GitHub (a run without a project has no git history)."
                )
            token = self.settings.github_token.get_secret_value() if self.settings.github_token else None
            branch = f"codewright/{stamp}"
            pr = await to_github(ws.work, repo, token, branch, f"Codewright: {name}", "Delivered by Codewright.")
            return {"location": pr, "detail": f"Pull request from branch {branch}."}
        raise DeliveryError(f"Unknown delivery target {target!r}.")
