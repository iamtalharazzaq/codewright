"""Outputs (delivery, CODEWRIGHT.md C7): local folder, ZIP, GitHub (branch + pull request), Google Drive.

Each returns where the result went, for the Done card. Nothing is overwritten: local copies get a new folder, GitHub
gets a new branch.
"""

from __future__ import annotations

import asyncio
import json
import mimetypes
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import httpx

from agent.tools.secrets import SKIP_DIRS as _SECRET_SKIP
from agent.tools.workspace import git
from connectors.inputs import auth_header, parse_github

# Codewright's own working folders (the knowledge graph, test reports) are not part of what the user gets.
SKIP_DIRS = _SECRET_SKIP | {"graphify-out", ".codewright"}


class DeliveryError(Exception):
    """Delivery failed; the message says why, for the user."""


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


def make_zip(src: Path, dest: Path) -> Path:
    """Zip a folder (without .git, node_modules, virtualenvs...)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(src.rglob("*")):
            rel = path.relative_to(src)
            if any(p in SKIP_DIRS for p in rel.parts) or path.is_symlink() or not path.is_file():
                continue
            zf.write(path, rel.as_posix())
    return dest


def to_local(src: Path, allowed: list[Path], name: str) -> Path:
    """Copy into the first allowed output folder (ALLOWED_OUTPUT_DIRS), as `<name>-<time>/`."""
    roots = [p for p in allowed if p.is_dir()]
    if not roots:
        raise DeliveryError("No output folder is allowed. Set ALLOWED_OUTPUT_DIRS in .env and restart.")
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in name)[:60] or "codewright"
    target = roots[0] / f"{safe}-{_stamp()}"
    shutil.copytree(
        src,
        target,
        ignore=shutil.ignore_patterns(".git", "node_modules", ".venv", "__pycache__", "graphify-out", ".codewright"),
    )
    return target


async def to_github(work: Path, repo_url: str, token: str | None, branch: str, title: str, body: str) -> str:
    """Push `work/`'s current commit as a new branch and open a pull request. Returns the PR URL."""
    if not token:
        raise DeliveryError("Delivering to GitHub needs a token: set GITHUB_TOKEN in .env and restart.")
    owner, repo = parse_github(repo_url)
    remote = f"https://github.com/{owner}/{repo}.git"
    try:
        git(work, *auth_header(token), "push", remote, f"HEAD:refs/heads/{branch}", timeout=600)
    except RuntimeError as exc:
        raise DeliveryError(f"Couldn't push to {owner}/{repo}: {exc}") from exc
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    async with httpx.AsyncClient(base_url="https://api.github.com", headers=headers, timeout=30) as http:
        info = await http.get(f"/repos/{owner}/{repo}")
        if info.status_code != 200:
            raise DeliveryError(f"GitHub returned {info.status_code} for {owner}/{repo}.")
        base = info.json().get("default_branch", "main")
        res = await http.post(
            f"/repos/{owner}/{repo}/pulls", json={"title": title, "head": branch, "base": base, "body": body}
        )
        if res.status_code not in (200, 201):
            raise DeliveryError(f"The branch {branch} was pushed, but opening the PR failed: {res.text[:200]}")
        url: str = res.json()["html_url"]
        return url


async def to_drive(archive: Path, access_token: str | None, name: str) -> str:
    """Upload a ZIP to the connected Google Drive (scope drive.file). Returns the file's link."""
    if not access_token:
        raise DeliveryError("Google Drive isn't connected yet: connect it in Settings.")
    metadata = f'{{"name": "{name}"}}'
    files: dict[str, tuple[str, bytes | str, str]] = {
        "metadata": ("metadata", metadata, "application/json; charset=UTF-8"),
        "file": (name, archive.read_bytes(), "application/zip"),
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(600, connect=15)) as http:
        res = await http.post(
            "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id,webViewLink",
            headers={"Authorization": f"Bearer {access_token}"},
            files=files,
        )
    if res.status_code not in (200, 201):
        raise DeliveryError(f"Google Drive upload failed ({res.status_code}): {res.text[:200]}")
    link: str = res.json().get("webViewLink") or f"https://drive.google.com/file/d/{res.json()['id']}/view"
    return link


DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
DRIVE_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id"
MAX_DRIVE_FILES = 3000
MAX_DRIVE_FILE_BYTES = 50 * 1024 * 1024


async def to_drive_folder(src: Path, access_token: str | None, name: str) -> str:
    """Upload a project as a folder tree (the same files as the ZIP, same exclusions) into a new Drive folder
    `name` (scope drive.file). Returns the folder's link."""
    if not access_token:
        raise DeliveryError("Google Drive isn't connected yet: connect it in Settings.")
    files = [
        p
        for p in sorted(src.rglob("*"))
        if p.is_file() and not p.is_symlink() and not any(part in SKIP_DIRS for part in p.relative_to(src).parts)
    ]
    if len(files) > MAX_DRIVE_FILES:
        raise DeliveryError(f"{len(files)} files is too many to upload one by one; deliver it as a ZIP instead.")
    if big := next((f for f in files if f.stat().st_size > MAX_DRIVE_FILE_BYTES), None):
        raise DeliveryError(f"{big.relative_to(src).as_posix()} is over 50 MB; deliver it as a ZIP instead.")
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=httpx.Timeout(300, connect=15), headers=headers) as http:

        async def make_folder(folder: str, parent: str | None) -> tuple[str, str]:
            body: dict[str, object] = {"name": folder, "mimeType": "application/vnd.google-apps.folder"}
            if parent:
                body["parents"] = [parent]
            res = await http.post(f"{DRIVE_FILES_URL}?fields=id,webViewLink", json=body)
            if res.status_code not in (200, 201):
                raise DeliveryError(f"Google Drive couldn't create the folder {folder} ({res.status_code}).")
            data = res.json()
            return data["id"], data.get("webViewLink") or f"https://drive.google.com/drive/folders/{data['id']}"

        root_id, link = await make_folder(name, None)
        folders: dict[str, str] = {"": root_id}
        for directory in sorted({p.relative_to(src).parent.as_posix() for p in files} - {"."}):
            parent = ""
            for part in directory.split("/"):  # parents sort first, so each one exists when its child needs it
                path = f"{parent}/{part}".lstrip("/")
                if path not in folders:
                    folders[path], _ = await make_folder(part, folders[parent])
                parent = path
        gate = asyncio.Semaphore(4)

        async def upload(path: Path) -> None:
            rel = path.relative_to(src)
            parent = folders["" if rel.parent.as_posix() == "." else rel.parent.as_posix()]
            kind = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            async with gate:
                res = await http.post(
                    DRIVE_UPLOAD_URL,
                    files={
                        "metadata": (
                            "metadata",
                            json.dumps({"name": path.name, "parents": [parent]}),
                            "application/json; charset=UTF-8",
                        ),
                        "file": (path.name, path.read_bytes(), kind),
                    },
                )
            if res.status_code not in (200, 201):
                raise DeliveryError(f"Google Drive upload of {rel.as_posix()} failed ({res.status_code}).")

        await asyncio.gather(*(upload(p) for p in files))
    return link
