"""Code review on seeded issues (CODEWRIGHT.md Phase 6 acceptance): a small project with known bugs is imported as a
ZIP, `/review-code` is typed in a project chat of a running stack, and the run's findings are graded against the
seeded issues. One file per fixture in `evals/data/review/` (Go and Python so far); add one for another language.

    python3 evals/review.py evals/data/review/seeded-go.json [--api http://localhost:8000/api] [--out evals/results/]

An issue is found when a finding is in its file, within `--window` lines of it (or of its span, `at` to `to`), and
says what the issue is about (a case-insensitive regex over the problem, why and fix). Each finding counts for one
issue at most. "Serious" issues should also come out critical or major. Major or critical findings in the fixture's
clean files are false alarms. Standard library only, so it runs anywhere.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import time
import urllib.request
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SERIOUS = ("critical", "major")


def call(api: str, method: str, path: str, body: Any = None, headers: dict[str, str] | None = None) -> Any:
    data = body if isinstance(body, bytes) else (json.dumps(body).encode() if body is not None else None)
    hdrs = headers or {"Content-Type": "application/json"}
    req = urllib.request.Request(  # noqa: S310  (the user's own API)
        api + path, method=method, data=data, headers=hdrs
    )
    with urllib.request.urlopen(req, timeout=600) as r:  # noqa: S310  (the user's own API)
        text = r.read()
        try:
            return json.loads(text) if text else None
        except ValueError:
            return text.decode()


def wait(what: str, check: Any, seconds: float, every: float = 3) -> Any:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if (result := check()) is not None:
            return result
        time.sleep(every)
    raise TimeoutError(f"{what}: nothing after {seconds:.0f}s")


def import_zip(api: str, repo: Path, name: str) -> str:
    """The fixture as a new project (a ZIP upload, like the New project form) → its id once it's ready."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(repo.rglob("*")):
            if f.is_file() and "__pycache__" not in f.parts:
                z.write(f, f"{repo.name}/{f.relative_to(repo).as_posix()}")
    boundary = uuid.uuid4().hex
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="kind"\r\n\r\nzip\r\n'.encode(),
        f'--{boundary}\r\nContent-Disposition: form-data; name="name"\r\n\r\n{name}\r\n'.encode(),
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{repo.name}.zip"\r\n'
        "Content-Type: application/zip\r\n\r\n".encode()
        + buf.getvalue()
        + b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    project = call(
        api, "POST", "/projects", b"".join(parts), {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    )

    def ready() -> str | None:
        p = call(api, "GET", f"/projects/{project['id']}")
        if p["status"] == "failed":
            raise RuntimeError(f"import failed: {p.get('error')}")
        return p["id"] if p["status"] == "ready" else None

    return str(wait("import", ready, 300))


def review(api: str, project: str, command: str, seconds: float) -> tuple[str, dict[str, Any]]:
    """`/review-code` in a new project chat → (run id, findings.json) once the run is complete."""
    conv = call(api, "POST", "/conversations", {"content": command, "project_id": project})["conversation"]["id"]

    def run_id() -> str | None:
        msgs = call(api, "GET", f"/conversations/{conv}")["messages"]
        return next((m["run_id"] for m in msgs if m.get("run_id")), None)

    rid = str(wait("run start", run_id, 120))

    def finished() -> dict[str, Any] | None:
        run = call(api, "GET", f"/runs/{rid}")
        if run["status"] in ("failed", "cancelled"):
            raise RuntimeError(f"run {rid} {run['status']}: {run.get('error')}")
        if run["pending"]:
            raise RuntimeError(f"run {rid} is waiting for an answer: {json.dumps(run['pending'])[:300]}")
        return run if run["status"] == "completed" else None

    wait("review", finished, seconds, every=5)
    path = next(a["path"] for a in call(api, "GET", f"/runs/{rid}")["artifacts"] if a["path"].endswith("findings.json"))
    found = call(api, "GET", f"/runs/{rid}/artifact?path={path}")
    return rid, found if isinstance(found, dict) else json.loads(found)


def line_of(repo: Path, file: str, snippet: str) -> int:
    for i, line in enumerate((repo / file).read_text(encoding="utf-8").splitlines(), 1):
        if snippet in line:
            return i
    raise ValueError(f"{snippet!r} isn't in {file}: fix the case file")


def grade(spec: dict[str, Any], repo: Path, findings: list[dict[str, Any]], window: int) -> dict[str, Any]:
    used: set[int] = set()
    issues: list[dict[str, Any]] = []
    for issue in spec["issues"]:
        line = line_of(repo, issue["file"], issue["at"])
        last = line_of(repo, issue["file"], issue["to"]) if issue.get("to") else line  # an issue spanning lines
        about = re.compile(issue["about"], re.I)
        candidates = [
            (max(0, line - int(f["line"]), int(f["line"]) - last), n)
            for n, f in enumerate(findings)
            if n not in used
            and f["file"] == issue["file"]
            and line - window <= int(f["line"]) <= last + window
            and about.search(" ".join(str(f.get(k, "")) for k in ("problem", "why", "fix")))
        ]
        hit = findings[min(candidates)[1]] if candidates else None
        if candidates:
            used.add(min(candidates)[1])
        issues.append(
            {
                "id": issue["id"],
                "file": issue["file"],
                "line": line,
                "found": hit is not None,
                "severity": hit["severity"] if hit else None,
                "severity_ok": hit is None or not issue.get("serious") or hit["severity"] in SERIOUS,
                "finding": {k: hit.get(k) for k in ("line", "severity", "category", "problem", "sources")}
                if hit
                else None,
            }
        )
    false_alarms = [f for f in findings if f["file"] in spec.get("clean", []) and f["severity"] in SERIOUS]
    others = [f for n, f in enumerate(findings) if n not in used and f not in false_alarms]
    return {"issues": issues, "false_alarms": false_alarms, "other_findings": others}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("case", type=Path, help="evals/data/review/<fixture>.json")
    parser.add_argument("--api", default="http://localhost:8000/api")
    parser.add_argument("--project", help="an already imported copy of the fixture (skips the import)")
    parser.add_argument("--run", help="grade a finished review run instead of starting one")
    parser.add_argument("--command", default="/review-code")
    parser.add_argument("--window", type=int, default=4)
    parser.add_argument("--wait", type=float, default=1800)
    parser.add_argument("--out", type=Path, default=Path("evals/results"))
    args = parser.parse_args()
    spec = json.loads(args.case.read_text(encoding="utf-8"))
    repo = ROOT / spec["repo"]

    start = time.monotonic()
    if args.run:
        project, rid = args.project or "", args.run
        path = next(
            a["path"] for a in call(args.api, "GET", f"/runs/{rid}")["artifacts"] if a["path"].endswith("findings.json")
        )
        result = call(args.api, "GET", f"/runs/{rid}/artifact?path={path}")
    else:
        project = args.project or import_zip(args.api, repo, f"{repo.name}-{datetime.now(UTC):%H%M%S}")
        rid, result = review(args.api, project, args.command, args.wait)
    g = grade(spec, repo, result["findings"], args.window)
    seconds = round(time.monotonic() - start)

    for i in g["issues"]:
        mark = "FOUND" if i["found"] else "MISS "
        sev = f" {i['severity']}" + ("" if i["severity_ok"] else " (should be critical/major)") if i["found"] else ""
        print(f"{mark} {i['id']:20} {i['file']}:{i['line']}{sev}")
    for f in g["false_alarms"]:
        print(f"FALSE ALARM {f['file']}:{f['line']} {f['severity']}: {f['problem']}")
    found = sum(i["found"] for i in g["issues"])
    serious_ok = sum(i["found"] and i["severity_ok"] for i in g["issues"])
    print(
        f"{args.case.stem}: {found}/{len(g['issues'])} seeded issues found ({serious_ok} with the right severity), "
        f"{len(g['false_alarms'])} false alarm(s) in clean files, {len(g['other_findings'])} other finding(s); "
        f"score {result['summary']['score']}/10; {seconds}s; run {rid}"
    )
    args.out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    out = {
        "case": args.case.stem,
        "project": project,
        "run": rid,
        "seconds": seconds,
        **g,
        "summary": result["summary"],
    }
    (args.out / f"review-{args.case.stem}-{stamp}.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
