"""Migration trial (CODEWRIGHT.md Section 5.12): what a migration does to a PostgreSQL sandbox database, measured.

The sandbox applies the project's existing migrations (and seed data, if the project has some) to a fresh database,
takes a snapshot, applies the new migration, takes another, applies its rollback and takes a third. This module has
the SQL for a snapshot, reads psql's table output and compares snapshots; the sandbox service runs the statements.
"""

from __future__ import annotations

import re
from typing import Any

SQL_ENGINES = {"postgres", "pgvector", "postgis"}  # the trial's SQL is PostgreSQL's (query_to_xml, pg_indexes)

# One row per table: its name, row count and a checksum of all its rows (order-independent).
TABLES_SQL = """
select table_name,
  (xpath('/row/c/text()', query_to_xml(format('select count(*) as c from %I.%I', table_schema, table_name), false, true, '')))[1]::text as n,
  (xpath('/row/c/text()', query_to_xml(format('select md5(coalesce(string_agg(t::text, '''' order by t::text), '''')) as c from %I.%I as t', table_schema, table_name), false, true, '')))[1]::text as h
from information_schema.tables where table_schema = 'public' and table_type = 'BASE TABLE' order by 1
"""  # noqa: E501

# One row per column, index and constraint.
SCHEMA_SQL = """
select 'column' as k, table_name || '.' || column_name || ' ' || data_type as v from information_schema.columns where table_schema = 'public'
union all select 'index', indexname from pg_indexes where schemaname = 'public'
union all select 'constraint', conname from pg_constraint c join pg_namespace n on n.oid = c.connamespace where n.nspname = 'public'
order by 1, 2
"""  # noqa: E501

_COUNT = re.compile(r"^\(\d+ rows?\)$")


def rows(output: str) -> list[list[str]]:
    """psql's aligned table → its data rows (header, rule and "(N rows)" dropped)."""
    lines = [ln for ln in output.splitlines() if ln.strip()]
    out: list[list[str]] = []
    seen_rule = False
    for line in lines:
        if re.fullmatch(r"[-+]+", line.strip()):
            seen_rule = True
            continue
        if not seen_rule or _COUNT.match(line.strip()):
            continue
        out.append([cell.strip() for cell in line.split("|")])
    return out


def snapshot(tables_output: str, schema_output: str) -> dict[str, Any]:
    tables = {r[0]: {"rows": r[1], "checksum": r[2]} for r in rows(tables_output) if len(r) >= 3}
    schema = sorted(f"{r[0]}: {r[1]}" for r in rows(schema_output) if len(r) >= 2)
    return {"tables": tables, "schema": schema}


def diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """What changed between two snapshots: tables, row counts, checksums (data rewritten) and schema objects."""
    bt, at = before["tables"], after["tables"]
    common = sorted(set(bt) & set(at))
    return {
        "tables_added": sorted(set(at) - set(bt)),
        "tables_removed": sorted(set(bt) - set(at)),
        "rows_changed": {t: [bt[t]["rows"], at[t]["rows"]] for t in common if bt[t]["rows"] != at[t]["rows"]},
        "data_changed": [t for t in common if bt[t]["checksum"] != at[t]["checksum"]],
        "schema_added": sorted(set(after["schema"]) - set(before["schema"])),
        "schema_removed": sorted(set(before["schema"]) - set(after["schema"])),
    }


def identical(before: dict[str, Any], after: dict[str, Any]) -> bool:
    d = diff(before, after)
    return not any(d.values())


def plan_kind(explain_output: str) -> str:
    """The way a query's plan reads the table, as the plan's own words (the first scan node)."""
    for kind in ("Index Only Scan", "Index Scan", "Bitmap Index Scan", "Seq Scan"):
        if kind in explain_output:
            return kind
    return "no scan found"
