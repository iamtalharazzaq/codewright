"""Outputs (delivery, CODEWRIGHT.md C7): local folder, ZIP, GitHub (branch + pull request), Google Drive.

Each returns where the result went, for the Done card. Nothing is overwritten: local copies get a new folder, GitHub
gets a new branch.
"""

from __future__ import annotations

import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import httpx

from agent.tools.secrets import SKIP_DIRS
from agent.tools.workspace import git
from connectors.inputs import auth_header, parse_github


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
    shutil.copytree(src, target, ignore=shutil.ignore_patterns(".git", "node_modules", ".venv", "__pycache__"))
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
