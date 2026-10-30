"use client";

import { useEffect, useState } from "react";

import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { getRun, listTraces, type RunDetail, type Trace } from "@/lib/api";
import { roleLabel } from "@/lib/roles";

import type { PlanRow } from "@/components/chat/plan-tab";

const STATE_WORD = { done: "Done", in_progress: "In progress", failed: "Failed", pending: "Waiting" } as const;

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-1">
      <h3 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">{title}</h3>
      <div className="text-sm">{children}</div>
    </section>
  );
}

/** What a step received, who it handed on to, and how it worked: its summary, model calls and files. */
export function AgentModal({
  row,
  rows,
  runId,
  onClose,
}: {
  row: PlanRow | null;
  rows: PlanRow[];
  runId: string | null;
  onClose: () => void;
}) {
  const [run, setRun] = useState<RunDetail | null>(null);
  const [traces, setTraces] = useState<Trace[]>([]);
  useEffect(() => {
    if (!row || !runId) return;
    const ctrl = new AbortController();
    getRun(runId, ctrl.signal)
      .then(setRun)
      .catch(() => undefined);
    listTraces(runId, ctrl.signal)
      .then(setTraces)
      .catch(() => undefined);
    return () => ctrl.abort();
  }, [row, runId]);

  const at = row ? rows.findIndex((r) => r.id === row.id) : -1;
  const before = at > 0 ? rows[at - 1] : null;
  const after = at >= 0 && at < rows.length - 1 ? rows[at + 1] : null;
  const info = row && run ? run.steps[row.id] : undefined;
  const mine = row ? traces.filter((t) => t.step === row.id) : [];
  const files = row && run ? run.artifacts.filter((a) => a.step === row.id) : [];
  const said = (r: PlanRow | null) => (r && run?.steps[r.id]?.summary ? `: ${run.steps[r.id].summary}` : "");
  const tokens = mine.reduce((n, t) => n + t.prompt_tokens + t.completion_tokens, 0);
  const seconds = mine.reduce((n, t) => n + t.latency_ms, 0) / 1000;

  return (
    <Dialog open={row !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        {row && (
          <>
            <div className="flex flex-col gap-1">
              <DialogTitle>{row.title}</DialogTitle>
              <DialogDescription>
                {row.role === "you" ? "You" : roleLabel(row.role)} · {STATE_WORD[row.status]}
              </DialogDescription>
            </div>
            <Section title="Received from">
              {before
                ? `${before.role === "you" ? "You" : roleLabel(before.role)} (${before.title})${said(before)}`
                : "Your request, straight from the chat."}
            </Section>
            <Section title="Sent to">
              {after
                ? `${after.role === "you" ? "You" : roleLabel(after.role)} (${after.title})${files.length ? ` with ${files.map((f) => f.title).join(", ")}` : ""}`
                : "Nobody: this is the last step."}
            </Section>
            <Section title="How it worked">
              {!runId ? (
                "Asked you the questions it still needed, with a recommended answer for each, before any work starts."
              ) : (
                <div className="flex flex-col gap-2">
                  <p>{info?.summary ?? (row.status === "pending" ? "Not started yet." : "Working on it…")}</p>
                  {mine.length > 0 ? (
                    <p className="text-muted-foreground">
                      {mine.length} model call{mine.length === 1 ? "" : "s"} · {tokens} tokens · {seconds.toFixed(1)}s
                    </p>
                  ) : (
                    row.status !== "pending" && <p className="text-muted-foreground">No model call: done by code.</p>
                  )}
                  {files.length > 0 && (
                    <ul className="list-disc pl-5">
                      {files.map((f) => (
                        <li key={f.path}>{f.title}</li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </Section>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
