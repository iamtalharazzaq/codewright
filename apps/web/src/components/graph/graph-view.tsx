"use client";

import { Loader2, Maximize2, RefreshCw, Search } from "lucide-react";
import Link from "next/link";
import { useMemo, useState, type FormEvent } from "react";

import { GraphCanvas, STATE_COLORS } from "@/components/graph/graph-canvas";
import { useProjectGraph } from "@/components/graph/use-project-graph";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { refreshGraph, searchCode, type SearchHit } from "@/lib/api";
import { cn } from "@/lib/utils";

const SUPPORT = /^(tests?|scripts|migrations|proto|docs|\(root\))$/;

/**
 * The project graph (CODEWRIGHT.md Sections 2.2 and 8.2). `compact` is the side panel's Graph tab; the full version
 * is the Graph explorer page with filters, node details, hygiene checks and code search.
 */
export function GraphView({
  projectId,
  compact = false,
  highlight = [],
}: {
  projectId: string;
  compact?: boolean;
  highlight?: string[];
}) {
  const { data, error, working, building, live, showVersion, goLive } = useProjectGraph(projectId);
  const [selected, setSelected] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [hideSupport, setHideSupport] = useState(true);

  const graph = data?.graph ?? null;
  const versions = data?.versions ?? [];
  const current = versions.find((v) => v.number === data?.version) ?? null;

  const hidden = useMemo(() => {
    const out = new Set<string>();
    for (const n of graph?.nodes ?? []) {
      if (hideSupport && SUPPORT.test(n.id)) out.add(n.id);
      if (filter && !n.id.toLowerCase().includes(filter.toLowerCase())) out.add(n.id);
    }
    return out;
  }, [graph, filter, hideSupport]);

  if (error && !graph) {
    return <p className="p-4 text-sm text-destructive">{error}</p>;
  }
  if (!data) {
    return (
      <p role="status" className="flex items-center gap-2 p-4 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" aria-hidden="true" />
        Loading graph…
      </p>
    );
  }
  if (!graph) {
    return (
      <div className="flex flex-col items-start gap-3 p-4 text-sm text-muted-foreground">
        <p>{building ? "Building the graph…" : "This project has no graph yet."}</p>
        {!building && (
          <Button size="sm" onClick={() => void refreshGraph(projectId)}>
            Build graph
          </Button>
        )}
      </div>
    );
  }

  const node = graph.nodes.find((n) => n.id === selected) ?? null;
  const out = graph.edges.filter((e) => e.source === selected);
  const into = graph.edges.filter((e) => e.target === selected);

  return (
    <div className={cn("flex min-h-0 flex-col gap-3", compact ? "h-full p-3" : "h-full")}>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="flex items-center gap-1.5 text-muted-foreground">
          {building ? (
            <>
              <Loader2 className="size-3.5 animate-spin" aria-hidden="true" /> updating…
            </>
          ) : (
            `${graph.nodes.length} modules · ${graph.edges.length} links`
          )}
        </span>
        <span className="flex-1" />
        <Button
          size="sm"
          variant="ghost"
          onClick={() => void refreshGraph(projectId)}
          disabled={building}
          aria-label="Rebuild graph"
          title="Rebuild graph"
        >
          <RefreshCw aria-hidden="true" />
        </Button>
        {compact && (
          <Link
            href={`/projects/${projectId}/graph`}
            className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
            aria-label="Open the graph explorer"
            title="Open the graph explorer"
          >
            <Maximize2 className="size-4" aria-hidden="true" />
          </Link>
        )}
      </div>

      {versions.length > 1 && (
        <div className="flex items-center gap-2 text-xs">
          <label htmlFor={`timeline-${projectId}`} className="shrink-0 text-muted-foreground">
            Version {data.version}/{versions.at(-1)?.number}
          </label>
          <input
            id={`timeline-${projectId}`}
            type="range"
            min={versions[0].number}
            max={versions.at(-1)!.number}
            value={data.version ?? 0}
            onChange={(e) => showVersion(Number(e.target.value))}
            className="min-w-0 flex-1 accent-primary"
          />
          <Button size="xs" variant={live ? "default" : "outline"} onClick={goLive}>
            Live
          </Button>
        </div>
      )}

      {!compact && (
        <div className="flex flex-wrap items-center gap-3">
          <Input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter modules"
            aria-label="Filter modules"
            className="h-8 w-48"
          />
          <div className="flex items-center gap-2">
            <Checkbox id="hide-support" checked={hideSupport} onCheckedChange={(c) => setHideSupport(Boolean(c))} />
            <Label htmlFor="hide-support" className="text-sm font-normal">
              Hide tests, scripts, migrations
            </Label>
          </div>
        </div>
      )}

      <Legend />

      <div className={cn("grid min-h-0 flex-1 gap-3", !compact && "lg:grid-cols-[1fr_20rem]")}>
        <GraphCanvas
          graph={graph}
          diff={current && current.number > versions[0].number ? current.diff : null}
          working={working}
          highlight={highlight}
          hidden={hidden}
          selected={selected}
          onSelect={setSelected}
          className={cn("min-h-72 rounded-lg border bg-card text-foreground", compact ? "h-full" : "h-[70vh]")}
        />
        {(!compact || node) && (
          <aside aria-label="Module details" className="flex min-h-0 flex-col gap-3 overflow-y-auto text-sm">
            {node ? (
              <>
                <div>
                  <h3 className="font-mono font-medium break-all">{node.id}</h3>
                  <p className="text-xs text-muted-foreground">
                    {node.file_count} files · {node.symbols} symbols
                    {Object.keys(node.languages).length > 0 && ` · ${Object.keys(node.languages).join(", ")}`}
                  </p>
                </div>
                <EdgeList title="Depends on" edges={out} field="target" onPick={setSelected} />
                <EdgeList title="Used by" edges={into} field="source" onPick={setSelected} />
                {!compact && (
                  <details>
                    <summary className="cursor-pointer text-xs text-muted-foreground">Files</summary>
                    <ul className="mt-1 font-mono text-xs">
                      {node.files.slice(0, 60).map((f) => (
                        <li key={f} className="truncate">
                          {f}
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
              </>
            ) : (
              <p className="text-muted-foreground">Click a module to see what it depends on and what uses it.</p>
            )}
            {!compact && current && <Hygiene hygiene={current.hygiene} />}
            {!compact && <CodeSearch projectId={projectId} />}
          </aside>
        )}
      </div>
    </div>
  );
}

function Legend() {
  const items: [string, string][] = [
    ["new", STATE_COLORS.added],
    ["changed", STATE_COLORS.changed],
    ["removed", STATE_COLORS.removed],
    ["being worked on", STATE_COLORS.working],
  ];
  return (
    <ul aria-label="Legend" className="flex flex-wrap gap-3 text-xs text-muted-foreground">
      {items.map(([label, color]) => (
        <li key={label} className="flex items-center gap-1">
          <span className="size-2.5 rounded-full" style={{ backgroundColor: color }} aria-hidden="true" />
          {label}
        </li>
      ))}
    </ul>
  );
}

function EdgeList({
  title,
  edges,
  field,
  onPick,
}: {
  title: string;
  edges: { source: string; target: string; weight: number; sources: { source: string }[] }[];
  field: "source" | "target";
  onPick: (id: string) => void;
}) {
  if (edges.length === 0) return null;
  return (
    <div>
      <h4 className="text-xs font-medium text-muted-foreground">{title}</h4>
      <ul className="flex flex-col">
        {[...edges]
          .sort((a, b) => b.weight - a.weight)
          .map((e) => (
            <li key={e[field]}>
              <button type="button" onClick={() => onPick(e[field])} className="font-mono text-xs hover:underline">
                {e[field]}
              </button>{" "}
              <span className="text-xs text-muted-foreground">
                {e.weight > 0 ? `${e.weight} refs` : "changed together"}
                {e.sources.length > 1 && ` · ${e.sources.map((s) => s.source).join(" + ")}`}
              </span>
            </li>
          ))}
      </ul>
    </div>
  );
}

function Hygiene({
  hygiene,
}: {
  hygiene: {
    code_files: number;
    files_without_symbols: string[];
    isolated_modules: string[];
    mutual_dependencies: string[];
  };
}) {
  return (
    <div className="rounded-lg border p-3">
      <h4 className="mb-1 text-xs font-medium">Graph checks</h4>
      <ul className="flex flex-col gap-0.5 text-xs text-muted-foreground">
        <li>{hygiene.code_files} code files read</li>
        <li>
          {hygiene.files_without_symbols.length === 0
            ? "Every code file contributed to the graph"
            : `${hygiene.files_without_symbols.length} code files gave nothing: ${hygiene.files_without_symbols.slice(0, 3).join(", ")}`}
        </li>
        <li>
          {hygiene.isolated_modules.length === 0
            ? "No isolated modules"
            : `Isolated: ${hygiene.isolated_modules.join(", ")}`}
        </li>
        <li>
          {hygiene.mutual_dependencies.length === 0
            ? "No modules depend on each other both ways"
            : `Both ways: ${hygiene.mutual_dependencies.join("; ")}`}
        </li>
      </ul>
    </div>
  );
}

function CodeSearch({ projectId }: { projectId: string }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!q.trim()) return;
    setBusy(true);
    try {
      setHits(await searchCode(projectId, q.trim()));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <form onSubmit={submit} className="flex gap-2">
        <Input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search the code"
          aria-label="Search the code"
          className="h-8"
        />
        <Button type="submit" size="sm" variant="outline" disabled={busy} aria-label="Search">
          {busy ? <Loader2 className="animate-spin" aria-hidden="true" /> : <Search aria-hidden="true" />}
        </Button>
      </form>
      {hits && (
        <ul aria-label="Search results" className="flex flex-col gap-2">
          {hits.length === 0 && <li className="text-xs text-muted-foreground">Nothing found.</li>}
          {hits.map((h) => (
            <li key={`${h.path}:${h.start_line}`} className="rounded-md border p-2">
              <p className="truncate font-mono text-xs">
                {h.path}:{h.start_line}
              </p>
              <pre className="mt-1 max-h-24 overflow-hidden text-[11px] leading-tight text-muted-foreground">
                {h.content.split("\n").slice(0, 6).join("\n")}
              </pre>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
