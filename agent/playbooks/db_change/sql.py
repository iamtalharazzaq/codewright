"""Helpers for Database change (CODEWRIGHT.md Section 5.12): the next migration's name, the schema the Database
Engineer is shown, risky statements, and the trial's report."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

NUMBERED = re.compile(r"^(?P<n>\d+)_(?P<name>.+)\.up\.sql$")
CREATE_TABLE = re.compile(r"create\s+table\s+(?:if\s+not\s+exists\s+)?(?:public\.)?\"?(\w+)\"?[^;]*;", re.I | re.S)
CREATE_INDEX = re.compile(r"create\s+(?:unique\s+)?index[^;]*;", re.I | re.S)
RISKY = re.compile(
    r"\b(drop\s+(table|column|schema|database)|truncate|delete\s+from|alter\s+column\s+\w+\s+type)\b", re.I
)
ENGINES = ("mysql", "mariadb", "mongo", "mongodb", "sqlite", "oracle", "sql server", "mssql", "cassandra", "dynamodb")
SCHEMA_BUDGET = 2400


def wants_engine_change(request: str) -> bool:
    low = request.lower()
    engine_words = [e for e in ENGINES if e in low]
    return (
        bool(engine_words)
        and bool(re.search(r"\b(to|into|->|→|from)\b", low))
        and ("postgres" in low or len(engine_words) > 1)
    )


def next_migration(existing: list[Path], work: Path, name: str) -> tuple[str, str]:
    """(`<folder>/<NNNN>_<name>.up.sql`, `...down.sql`), numbered after the last existing migration."""
    last = existing[-1] if existing else None
    folder = last.parent.relative_to(work).as_posix() if last else "migrations"
    m = NUMBERED.match(last.name) if last else None
    width = len(m.group("n")) if m else 4
    number = str(int(m.group("n")) + 1 if m else 1).zfill(width)
    stem = f"{folder}/{number}_{slug(name)}"
    return stem + ".up.sql", stem + ".down.sql"


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40] or "change"


def schema_excerpt(migrations: list[Path], request: str) -> str:
    """The CREATE TABLE and CREATE INDEX statements that matter to the request, within the model's small context:
    tables the request names first, then the rest while there is room."""
    words = set(re.findall(r"[a-z_]+", request.lower()))
    tables: list[tuple[str, str]] = []
    indexes: list[str] = []
    for f in migrations:
        text = f.read_text(encoding="utf-8", errors="replace")
        tables += [(m.group(1), re.sub(r"\s+", " ", m.group(0))) for m in CREATE_TABLE.finditer(text)]
        indexes += [re.sub(r"\s+", " ", m.group(0)) for m in CREATE_INDEX.finditer(text)]
    named = [t for t in tables if t[0].lower() in words or t[0].lower().rstrip("s") in words]
    out, used = [], 0
    for _, stmt in [*named, *[t for t in tables if t not in named]]:
        if used + len(stmt) > SCHEMA_BUDGET:
            break
        out.append(stmt)
        used += len(stmt)
    names = {t[0].lower() for t in named}
    kept_indexes = [i for i in indexes if any(n in i.lower() for n in names)][:6]
    return "\n".join([*out, *kept_indexes])


def risky(*sql: str) -> list[str]:
    return sorted({m.group(1).lower() for s in sql for m in RISKY.finditer(s)})


def trial_markdown(trial: dict[str, Any] | None) -> str:
    if not trial or trial.get("ok") is None:
        why = (trial or {}).get("error", "the trial did not run")
        return f"⚠️ **Not applied to a sandbox database** ({why}); the SQL is unverified."
    lines = []
    up, down = trial["up"], trial["down"]
    lines.append(
        "✅ **Migration applied cleanly** to a fresh database"
        + (f" (seed data: {', '.join(trial['seeded'])}; {trial['rows_before']} rows before)" if trial["seeded"] else "")
        if up["ok"]
        else f"❌ **Migration failed:** {up['error'][:300]}"
    )
    c = trial["changes"]
    if up["ok"]:
        if c["schema_added"] or c["schema_removed"] or c["tables_added"] or c["tables_removed"]:
            lines += [f"- added: {', '.join(c['schema_added'][:8])}"] if c["schema_added"] else []
            lines += [f"- removed: {', '.join(c['schema_removed'][:8])}"] if c["schema_removed"] else []
        lines.append(
            "✅ **Data unchanged:** every table keeps its row count and checksum."
            if not c["rows_changed"] and not c["data_changed"]
            else f"⚠️ **Data changed** in: {', '.join(sorted({*c['rows_changed'], *c['data_changed']}))}"
        )
        for q in trial["queries"]:
            lines.append(f"- `{q['query'][:80]}`: {q['before']} → {q['after']}")
    if up["ok"]:
        lines.append(
            "✅ **Rollback restores the starting state exactly.**"
            if trial["rollback_restores"]
            else "❌ **Rollback does not restore the starting state:** "
            + str(down["error"][:200] or trial["rollback_differences"])
        )
    return "\n".join(lines)


def failure_summary(trial: dict[str, Any]) -> str:
    """What to tell the model when the trial failed, so its next SQL is better."""
    if not trial["up"]["ok"]:
        return f"The up migration failed in PostgreSQL:\n{trial['up']['error']}"
    if not trial["down"]["ok"]:
        return f"The down migration failed in PostgreSQL:\n{trial['down']['error']}"
    return f"After the down migration the database is not as it started: {trial['rollback_differences']}"
