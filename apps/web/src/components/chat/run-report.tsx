"use client";

import { Download } from "lucide-react";
import { useEffect, useState } from "react";

import { Markdown } from "@/components/chat/markdown";
import { getRun, getRunArtifact, type ArtifactRef } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * The Report tab for a run started from this chat (CODEWRIGHT.md Section 2.2): its reports and diagrams (review
 * findings, the audit, the As-Is, generated docs), rendered as Markdown with their diagrams. Reloads as the run moves.
 */
export function RunReport({ runId, tick }: { runId: string; tick: number }) {
  const [artifacts, setArtifacts] = useState<ArtifactRef[]>([]);
  const [chosen, setChosen] = useState<string | null>(null);
  const [text, setText] = useState<string>("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    getRun(runId, ctrl.signal)
      .then((run) => {
        const shown = run.artifacts.filter((a) => a.kind === "report" || a.kind === "diagram");
        setArtifacts(shown);
        setChosen((c) => (c && shown.some((a) => a.path === c) ? c : (shown.at(-1)?.path ?? null)));
      })
      .catch((e: unknown) => {
        if (!ctrl.signal.aborted) setError(e instanceof Error ? e.message : String(e));
      });
    return () => ctrl.abort();
  }, [runId, tick]);

  useEffect(() => {
    if (!chosen) return;
    const ctrl = new AbortController();
    getRunArtifact(runId, chosen, ctrl.signal)
      .then((t) => {
        setText(t);
        setError(null);
      })
      .catch((e: unknown) => {
        if (!ctrl.signal.aborted) setError(e instanceof Error ? e.message : String(e));
      });
    return () => ctrl.abort();
  }, [runId, chosen, tick]);

  if (error) {
    return (
      <p role="alert" className="p-4 text-sm text-destructive">
        {error}
      </p>
    );
  }
  if (!artifacts.length) {
    return (
      <p className="p-6 text-center text-sm text-muted-foreground">The report appears here when the run writes it.</p>
    );
  }
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center gap-1 border-b p-2" role="tablist" aria-label="Reports">
        {artifacts.map((a) => (
          <button
            key={a.path}
            type="button"
            role="tab"
            aria-selected={a.path === chosen}
            onClick={() => setChosen(a.path)}
            className={cn(
              "rounded-md px-2 py-1 text-xs",
              a.path === chosen ? "bg-muted font-medium text-foreground" : "text-muted-foreground hover:bg-muted/60",
            )}
          >
            {a.title}
          </button>
        ))}
        {chosen && (
          <a
            href={`/api/runs/${runId}/artifact?path=${encodeURIComponent(chosen)}`}
            download={chosen.split("/").at(-1)}
            className="ml-auto flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-muted"
          >
            <Download className="size-3.5" aria-hidden="true" />
            Download
          </a>
        )}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-4 text-sm">
        <Markdown>{text}</Markdown>
      </div>
    </div>
  );
}
