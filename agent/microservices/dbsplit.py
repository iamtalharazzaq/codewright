# ruff: noqa: E501, RUF028, S608
"""The database split of a microservices conversion (CODEWRIGHT.md 5.18 step 8), as reviewable SQL.

One migration (up and down) per service that owns tables, produced from the design and the SQL the code contains,
not by a model: a schema and a role for the service, its tables moved into the schema, a compatibility view left in
`public` so the monolith keeps working until its cut-over, the foreign keys that cross a service boundary dropped
(the id stays; the other service's data is read through its API or its events), an **outbox** for the events the
service produces, a table of **processed events** for the ones it consumes (idempotent consumers) and a state table
for the sagas it orchestrates.

The migrations are applied in build order and rolled back in the reverse order. Nothing here runs against a
database; the playbook tries each one (up, then down) on a fresh PostgreSQL in the sandbox when there is one.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agent.decomposition import boundaries as b
from agent.microservices.foundation import safe_name, service_names

MIGRATIONS = "migrations/microservices"
CREATE_TABLE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"`]?(?:\w+\.)?(\w+)[\"`]?\s*\((.*?)\)\s*;", re.I | re.S
)
TABLE_FK = re.compile(
    r"(?:CONSTRAINT\s+[\"`]?(\w+)[\"`]?\s+)?FOREIGN\s+KEY\s*\(\s*[\"`]?(\w+)[\"`]?\s*\)\s*REFERENCES\s+[\"`]?(?:\w+\.)?(\w+)[\"`]?\s*\(\s*[\"`]?(\w+)[\"`]?\s*\)",
    re.I,
)
COLUMN_FK = re.compile(
    r"^[\"`]?(\w+)[\"`]?\s+[^,]*?REFERENCES\s+[\"`]?(?:\w+\.)?(\w+)[\"`]?\s*\(\s*[\"`]?(\w+)[\"`]?\s*\)", re.I | re.S
)


def q(name: str) -> str:
    """A quoted SQL identifier (`order` is a reserved word)."""
    return '"' + name.replace('"', '""') + '"'


def _split_top(body: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    cur: list[str] = []
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur).strip())
    return [p for p in parts if p]


def scan_fks(work: Path) -> list[dict[str, str]]:
    """Foreign keys declared in the project's SQL: table, column, referenced table and column, constraint name (the
    PostgreSQL default `<table>_<column>_fkey` when the SQL does not name it)."""
    found: list[dict[str, str]] = []
    for path in sorted(work.rglob("*.sql")):
        rel = path.relative_to(work).parts
        if any(p in b.SKIP for p in rel) or rel[:2] == tuple(MIGRATIONS.split("/")):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in CREATE_TABLE.finditer(text):
            table = m.group(1).lower()
            for part in _split_top(m.group(2)):
                if t := TABLE_FK.search(part):
                    col = t.group(2).lower()
                    found.append(
                        {
                            "table": table,
                            "column": col,
                            "ref_table": t.group(3).lower(),
                            "ref_column": t.group(4).lower(),
                            "constraint": (t.group(1) or f"{table}_{col}_fkey").lower(),
                        }  # fmt: skip
                    )
                elif c := COLUMN_FK.match(part):
                    col = c.group(1).lower()
                    found.append(
                        {
                            "table": table,
                            "column": col,
                            "ref_table": c.group(2).lower(),
                            "ref_column": c.group(3).lower(),
                            "constraint": f"{table}_{col}_fkey",
                        }  # fmt: skip
                    )
    return found


def split_plan(
    work: Path, rules: dict[str, Any], design: dict[str, Any], platform: dict[str, Any], order: list[str]
) -> dict[str, Any]:
    """Per service (in build order): its tables, the foreign keys to drop, the outbox / inbox / saga tables; and what
    could not be assigned (a table written by several modules and owned by none)."""
    tables = b.scan_tables(work, rules)
    owner: dict[str, str | None] = {
        t: (v["owner"] or (v["writers"][0] if len(v["writers"]) == 1 else None)) for t, v in tables.items()
    }
    backend = set(service_names(design))
    fks = scan_fks(work)
    events = platform.get("events", [])
    sagas = platform.get("sagas", [])
    entries = []
    for name in order:
        mine = sorted(t for t, o in owner.items() if o == name)
        drops = [
            f
            for f in fks
            if (owner.get(f["table"]), owner.get(f["ref_table"])) != (None, None)
            and owner.get(f["table"]) != owner.get(f["ref_table"])
            and (
                (owner.get(f["table"]) == name) or (owner.get(f["table"]) is None and owner.get(f["ref_table"]) == name)
            )
        ]
        produces = [e["event"] for e in events if e["producer"] == name]
        consumes = [e["event"] for e in events if name in e["consumers"]]
        orchestrates = [s["name"] for s in sagas if s["orchestrator"] == name]
        if mine or produces or consumes or orchestrates:
            entries.append(
                {
                    "service": name,
                    "schema": safe_name(name),
                    "tables": mine,
                    "drop_fks": drops,
                    "produces": produces,
                    "consumes": consumes,
                    "sagas": orchestrates,
                }  # fmt: skip
            )
    shared = sorted(
        t
        for t, v in tables.items()
        if owner[t] is None and len(v["writers"]) > 1 and any(w in backend for w in v["writers"])
    )
    return {"services": entries, "unassigned_tables": shared, "foreign_keys": len(fks)}


def render(entry: dict[str, Any], owners: dict[str, str | None]) -> tuple[str, str]:
    """(up, down) SQL for one service of the split plan. `owners` is table → the schema it lives in after the split
    (None = still public), used to re-create dropped foreign keys on the way back."""
    schema, role = q(entry["schema"]), q("svc_" + entry["schema"])
    up = [
        f"-- Codewright: the {entry['service']} service gets its own schema (CODEWRIGHT.md 5.18 step 8). Review it, then apply.",
        "-- Roll the migrations of a conversion back in the reverse order of applying them.",
        f"CREATE SCHEMA IF NOT EXISTS {schema};",
        f"DO $$ BEGIN CREATE ROLE {role} NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;  -- set a password out of band",
    ]
    down: list[str] = [f"-- Undo the {entry['service']} split."]
    for fk in entry["drop_fks"]:
        where = q(owners.get(fk["table"]) or "public")
        up.append(
            f"ALTER TABLE {where}.{q(fk['table'])} DROP CONSTRAINT IF EXISTS {q(fk['constraint'])};  -- crosses a service boundary"
        )
    for t in entry["tables"]:
        up += [
            f"ALTER TABLE public.{q(t)} SET SCHEMA {schema};",
            f"CREATE VIEW public.{q(t)} AS SELECT * FROM {schema}.{q(t)};  -- the monolith keeps working until the cut-over",
        ]
    up += [
        f"GRANT USAGE ON SCHEMA {schema} TO {role};",
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {schema} TO {role};",
    ]
    if entry["produces"]:
        up.append(
            f"CREATE TABLE IF NOT EXISTS {schema}.outbox (id uuid PRIMARY KEY, type text NOT NULL, payload jsonb NOT NULL, "
            "created_at timestamptz NOT NULL DEFAULT now(), published_at timestamptz);  -- written in the same transaction as the change"
        )
    if entry["consumes"]:
        up.append(
            f"CREATE TABLE IF NOT EXISTS {schema}.processed_events (event_id text PRIMARY KEY, "
            "processed_at timestamptz NOT NULL DEFAULT now());  -- an event already seen is skipped"
        )
    if entry["sagas"]:
        up.append(
            f"CREATE TABLE IF NOT EXISTS {schema}.saga_state (id uuid PRIMARY KEY, name text NOT NULL, step integer NOT NULL, "
            "status text NOT NULL CHECK (status IN ('running', 'completed', 'compensating', 'failed')), "
            "context jsonb NOT NULL DEFAULT '{}', updated_at timestamptz NOT NULL DEFAULT now());"
        )
    for extra in ("outbox", "processed_events", "saga_state"):
        down.append(f"DROP TABLE IF EXISTS {schema}.{extra};")
    for t in reversed(entry["tables"]):
        down += [f"DROP VIEW IF EXISTS public.{q(t)};", f"ALTER TABLE {schema}.{q(t)} SET SCHEMA public;"]
    for fk in entry["drop_fks"]:
        child = "public"  # after the tables are moved back; the referenced table's schema at that moment is public too
        down.append(
            f"ALTER TABLE {child}.{q(fk['table'])} ADD CONSTRAINT {q(fk['constraint'])} FOREIGN KEY ({q(fk['column'])}) "
            f"REFERENCES public.{q(fk['ref_table'])} ({q(fk['ref_column'])});"
        )
    down += [
        f"REVOKE ALL ON SCHEMA {schema} FROM {role};",
        f"DROP SCHEMA IF EXISTS {schema};",
        f"DROP ROLE IF EXISTS {role};",
    ]
    return "\n".join(up) + "\n", "\n".join(down) + "\n"


def migration_files(plan: dict[str, Any]) -> dict[str, str]:
    """`migrations/microservices/NNN_<service>.up.sql` / `.down.sql`, numbered in build order."""
    owners: dict[str, str | None] = {t: e["schema"] for e in plan["services"] for t in e["tables"]}
    files: dict[str, str] = {}
    for i, entry in enumerate(plan["services"], 1):
        up, down = render(entry, owners)
        files[f"{MIGRATIONS}/{i:03d}_{entry['schema']}.up.sql"] = up
        files[f"{MIGRATIONS}/{i:03d}_{entry['schema']}.down.sql"] = down
    return files


def brief(plan: dict[str, Any]) -> str:
    lines = []
    for e in plan["services"]:
        bits = [f"{len(e['tables'])} table(s)" if e["tables"] else "no tables"]
        bits += [f"{len(e['drop_fks'])} cross-service foreign key(s) dropped"] if e["drop_fks"] else []
        bits += ["outbox"] if e["produces"] else []
        bits += ["processed-events table"] if e["consumes"] else []
        bits += [f"saga state ({', '.join(e['sagas'])})"] if e["sagas"] else []
        lines.append(f"- **{e['service']}** (schema `{e['schema']}`): " + ", ".join(bits))
    if plan["unassigned_tables"]:
        lines.append(
            "⚠️ Tables written by several modules and owned by none, left in `public`: "
            + ", ".join(f"`{t}`" for t in plan["unassigned_tables"])
        )
    return "\n".join(lines) or "No service owns a table, so there is nothing to split."
