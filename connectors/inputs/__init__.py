"""Inputs: each function fills an empty folder with a project's files, or raises `InputError` with a clear reason.

Everything brought in is data, never instructions. ZIPs are checked before anything is written (path traversal,
links, size, file count, compression ratio).
"""

from __future__ import annotations

import base64
import re
import shutil
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import httpx

from agent.tools.workspace import git


class InputError(Exception):
    """The source can't be imported; the message says why, for the user."""


@dataclass(frozen=True)
class ZipLimits:
    max_files: int = 20_000
    max_total_bytes: int = 500 * 1024 * 1024
    max_file_bytes: int = 100 * 1024 * 1024
    max_ratio: float = 200.0  # uncompressed / compressed, per file: a higher ratio looks like a zip bomb


def _check_zip(zf: zipfile.ZipFile, limits: ZipLimits) -> list[zipfile.ZipInfo]:
    infos = zf.infolist()
    if len(infos) > limits.max_files:
        raise InputError(f"The ZIP has {len(infos)} entries; the limit is {limits.max_files}.")
    total = 0
    for info in infos:
        name = info.filename
        parts = PurePosixPath(name.replace("\\", "/")).parts
        if name.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", name) or ".." in parts:
            raise InputError(f"Rejected: the ZIP contains an unsafe path ({name!r}).")
        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise InputError(f"Rejected: the ZIP contains a symbolic link ({name!r}).")
        if info.file_size > limits.max_file_bytes:
            raise InputError(f"Rejected: {name!r} is larger than {limits.max_file_bytes // 2**20} MB.")
        if info.compress_size and info.file_size / info.compress_size > limits.max_ratio and info.file_size > 2**20:
            raise InputError(f"Rejected: {name!r} is compressed suspiciously well (possible ZIP bomb).")
        total += info.file_size
        if total > limits.max_total_bytes:
            raise InputError(f"Rejected: the ZIP unpacks to more than {limits.max_total_bytes // 2**20} MB.")
    return infos


def extract_zip(archive: Path, dest: Path, limits: ZipLimits | None = None) -> Path:
    """Unpack safely into `dest`. A ZIP with a single top folder is unwrapped (GitHub "Download ZIP" layout)."""
    limits = limits or ZipLimits()
    try:
        zf = zipfile.ZipFile(archive)
    except zipfile.BadZipFile as exc:
        raise InputError("That file isn't a valid ZIP.") from exc
    with zf:
        infos = _check_zip(zf, limits)
        dest.mkdir(parents=True, exist_ok=True)
        written = 0
        for info in infos:
            target = (dest / info.filename).resolve()
            if not target.is_relative_to(dest.resolve()):
                raise InputError(f"Rejected: the ZIP contains an unsafe path ({info.filename!r}).")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, target.open("wb") as out:
                while chunk := src.read(1 << 20):  # count real bytes: headers can lie about sizes
                    written += len(chunk)
                    if written > limits.max_total_bytes:
                        raise InputError("Rejected: the ZIP unpacks to more than allowed.")
                    out.write(chunk)
    entries = [p for p in dest.iterdir() if p.name not in ("__MACOSX",)]
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    if not entries:
        raise InputError("The ZIP is empty.")
    return dest


_GITHUB = re.compile(r"^https://github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")


def parse_github(url: str) -> tuple[str, str]:
    match = _GITHUB.match(url.strip())
    if not match:
        raise InputError("Use a GitHub repository URL like https://github.com/owner/repo.")
    return match.group(1), match.group(2)


def auth_header(token: str | None) -> list[str]:
    """git `-c` options that send the token as a header, so it never appears in a URL, a remote or a log."""
    if not token:
        return []
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return ["-c", f"http.extraHeader=Authorization: Basic {basic}"]


def clone_github(url: str, dest: Path, token: str | None = None, branch: str | None = None) -> Path:
    owner, repo = parse_github(url)
    args = [*auth_header(token), "clone", "--depth", "1", *(["--branch", branch] if branch else [])]
    try:
        git(dest.parent, *args, f"https://github.com/{owner}/{repo}.git", dest.name, timeout=600)
    except RuntimeError as exc:
        hint = " It may be private: add a GitHub token in .env (GITHUB_TOKEN)." if not token else ""
        raise InputError(f"Couldn't clone {owner}/{repo}.{hint} ({exc})") from exc
    return dest  # keeps .git: work/ continues the repo's history, so delivery can open a pull request


def copy_local(path: str, allowed_root: Path | None, dest: Path) -> Path:
    """Copy a folder from the mounted local source folder (LOCAL_SOURCE_DIR), never from anywhere else."""
    if allowed_root is None or not allowed_root.is_dir():
        raise InputError("No local folder is shared with Codewright. Set LOCAL_SOURCE_DIR in .env and restart.")
    root = allowed_root.resolve()
    source = (root / path.strip().lstrip("/")).resolve()
    if not source.is_relative_to(root):
        raise InputError("That folder is outside the shared local folder.")
    if not source.is_dir():
        raise InputError(f"Folder not found: {path!r} (paths are relative to the shared local folder).")
    shutil.copytree(source, dest, symlinks=False, ignore=shutil.ignore_patterns(".git", "node_modules", ".venv"))
    return dest


_DRIVE_ID = re.compile(r"(?:/d/|[?&]id=)([\w-]{20,})")


def drive_file_id(link: str) -> str:
    match = _DRIVE_ID.search(link)
    if not match:
        raise InputError("Use a Google Drive file link, e.g. https://drive.google.com/file/d/<id>/view.")
    return match.group(1)


async def download_drive_zip(link: str, dest: Path, access_token: str | None = None) -> Path:
    """Download a ZIP from Drive: with the connected account's token, or as a public "anyone with the link" file."""
    file_id = drive_file_id(link)
    if access_token:
        url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
        headers = {"Authorization": f"Bearer {access_token}"}
    else:
        url = f"https://drive.usercontent.google.com/download?id={file_id}&export=download&confirm=t"
        headers = {}
    async with (
        httpx.AsyncClient(timeout=httpx.Timeout(600, connect=15), follow_redirects=True) as http,
        http.stream("GET", url, headers=headers) as res,
    ):
        if res.status_code != 200:
            raise InputError(f"Google Drive returned {res.status_code}. Is the file shared or Drive connected?")
        with dest.open("wb") as out:
            async for chunk in res.aiter_bytes():
                out.write(chunk)
    if not zipfile.is_zipfile(dest):
        raise InputError("The Drive file isn't a ZIP (or isn't shared publicly). Share a ZIP of the project.")
    return dest
