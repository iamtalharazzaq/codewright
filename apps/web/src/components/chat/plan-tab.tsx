"use client";

import { CheckCircle2, Circle, Loader2, XCircle } from "lucide-react";
import { useEffect, useState } from "react";

import { getRun, type ChatMessage, type PlanItem } from "@/lib/api";
import { roleLabel } from "@/lib/roles";
import { cn } from "@/lib/utils";

type Status = PlanItem["status"];
export interface PlanRow {
  id: string;
  title: string;
  role: string;
  status: Status;
}

/**
 * The handoffs before a run starts, read from the chat: the request goes to the Product Manager to gather the missing
 * details (in progress while the questions are open), who is done once they are answered and the card is shown, and
 * then you confirm it. Nothing yet → no rows.
 */
export function intakeRows(messages: ChatMessage[], hasRun: boolean): PlanRow[] {
  const last = (kind: ChatMessage["kind"]) => [...messages].reverse().find((m) => m.kind === kind);
  const questions = last("questions");
  const confirm = last("confirm");
  if (!questions && !confirm && !hasRun) return [];
  const gathered = !!confirm || hasRun;
  const confirmed = hasRun || (!!confirm && !["open", "changing"].includes(confirm.data.state ?? "open"));
  return [
    {
      id: "gather",
      title: "Gather the missing details",
      role: "product_manager",
      status: gathered ? "done" : "in_progress",
    },
    {
      id: "confirm",
      title: "Confirm what to make",
      role: "you",
      status: confirmed ? "done" : gathered ? "in_progress" : "pending",
    },
  ];
}

const ICON: Record<Status, React.ReactNode> = {
  done: <CheckCircle2 className="size-4 text-green-600" aria-hidden="true" />,
  in_progress: <Loader2 className="size-4 animate-spin text-primary" aria-hidden="true" />,
  failed: <XCircle className="size-4 text-destructive" aria-hidden="true" />,
  pending: <Circle className="size-4 text-muted-foreground" aria-hidden="true" />,
};
const STATE_WORD: Record<Status, string> = {
  done: "Done",
  in_progress: "In progress",
  failed: "Failed",
  pending: "Waiting",
};

/** The Plan tab beside the chat: who has the request now, then the run's own steps with their live state. */
export function PlanTab({
  messages,
  runId,
  runTick,
}: {
  messages: ChatMessage[];
  runId: string | null;
  runTick: number;
}) {
  const [steps, setSteps] = useState<PlanItem[]>([]);
  useEffect(() => {
    if (!runId) return;
    const ctrl = new AbortController();
    getRun(runId, ctrl.signal)
      .then((run) => setSteps(run.plan))
      .catch(() => undefined);
    return () => ctrl.abort();
  }, [runId, runTick]);

  const rows: PlanRow[] = [...intakeRows(messages, !!runId), ...(runId ? steps : [])];
  if (rows.length === 0) {
    return (
      <p className="p-6 text-center text-sm text-muted-foreground">The plan and its live checklist appear here.</p>
    );
  }
  return (
    <ol aria-label="Plan" className="flex flex-col gap-1 overflow-y-auto p-4">
      {rows.map((r) => (
        <li key={r.id} className="flex items-start gap-3 rounded-md px-2 py-2">
          <span className="mt-0.5">{ICON[r.status]}</span>
          <span className="flex min-w-0 flex-col">
            <span className={cn("text-sm", r.status === "pending" ? "text-muted-foreground" : "font-medium")}>
              {r.title}
              <span className="sr-only"> ({STATE_WORD[r.status]})</span>
            </span>
            <span className="text-xs text-muted-foreground">{r.role === "you" ? "You" : roleLabel(r.role)}</span>
          </span>
        </li>
      ))}
    </ol>
  );
}
