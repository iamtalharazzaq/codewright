"use client";

import { Ban, CheckCircle2, Circle, Loader2, PauseCircle, ShieldCheck, Wifi, WifiOff } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { GateCard, LLMUnavailableCard } from "@/components/runs/pending-card";
import { useRunEvents } from "@/components/runs/use-run-events";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  cancelRun,
  getRun,
  getWorkflow,
  listTraces,
  PROFILE_LABEL,
  type RunDetail,
  type RunEvent,
  type Trace,
  type Workflow,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const AUDIT_FLOW = [
  "intake",
  "gate1",
  "baseline",
  "as_is",
  "gate2",
  "to_be",
  "gate3",
  "languages",
  "gate4",
  "audit_report",
  "gate8",
  "deliver",
];
const CONVERSION_FLOW = [
  ...AUDIT_FLOW.slice(0, 9),
  "foundation",
  "build_service",
  "gate5",
  "db_split",
  "gate6",
  "frontend",
  "gate7",
  "report",
  "gate8",
  "deliver",
];

const ROLE_LABEL: Record<string, string> = {
  business_analyst: "Business Analyst",
  qa_engineer: "QA Engineer",
  solution_architect: "Solution Architect",
  technical_writer: "Technical Writer",
  devops_engineer: "DevOps Engineer",
  backend_developer: "Backend Developer",
  database_engineer: "Database Engineer",
  frontend_developer: "Frontend Developer",
  release_manager: "Release Manager",
};

type ItemState = "done" | "running" | "waiting" | "todo";

export function RunView({ runId }: { runId: string }) {
  const [run, setRun] = useState<RunDetail | null>(null);
  const [workflow, setWorkflow] = useState<Workflow | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { events, connected } = useRunEvents(runId);

  const refresh = useCallback(() => {
    getRun(runId)
      .then(setRun)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, [runId]);

  useEffect(() => {
    getWorkflow()
      .then(setWorkflow)
      .catch(() => undefined);
  }, []);

  // Every new event may change status, pending prompt or usage.
  const lastEventId = events.at(-1)?.id;
  useEffect(() => {
    refresh();
  }, [refresh, lastEventId]);

  if (error && !run) {
    return (
      <p role="alert" className="text-sm text-destructive">
        {error}
      </p>
    );
  }
  if (!run || !workflow) {
    return (
      <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" aria-hidden="true" /> Loading run…
      </p>
    );
  }

  const active = run.status === "running" || run.status === "waiting" || run.status === "created";

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex flex-col gap-1">
          <h1 className="font-heading text-2xl font-semibold tracking-tight">
            {run.mode === "audit" ? "Architecture audit" : "Full conversion"}
          </h1>
          <p className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            <span className="font-mono">{run.id.slice(0, 8)}</span>
            <StatusBadge status={run.status} />
            <span>{PROFILE_LABEL[run.llm_profile]}</span>
            <span className="flex items-center gap-1" title={connected ? "Live updates connected" : "Reconnecting…"}>
              {connected ? (
                <Wifi className="size-3.5 text-success" aria-hidden="true" />
              ) : (
                <WifiOff className="size-3.5" aria-hidden="true" />
              )}
              <span className="sr-only">{connected ? "Live updates connected" : "Live updates reconnecting"}</span>
            </span>
          </p>
        </div>
        {active && (
          <Button
            variant="outline"
            onClick={() => {
              void cancelRun(run.id).then(refresh);
            }}
          >
            <Ban aria-hidden="true" />
            Cancel run
          </Button>
        )}
      </header>

      {run.error && (
        <p
          role="alert"
          className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive"
        >
          {run.error}
        </p>
      )}

      {run.status === "waiting" && run.pending?.kind === "gate" && (
        <GateCard key={JSON.stringify(run.pending)} runId={run.id} prompt={run.pending} onAnswered={refresh} />
      )}
      {run.status === "waiting" && run.pending?.kind === "llm_unavailable" && (
        <LLMUnavailableCard runId={run.id} prompt={run.pending} onAnswered={refresh} />
      )}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <Timeline run={run} workflow={workflow} events={events} />
        <div className="flex flex-col gap-6">
          <UsageCard run={run} />
          <Tabs defaultValue="activity">
            <TabsList>
              <TabsTrigger value="activity">Activity</TabsTrigger>
              <TabsTrigger value="traces">LLM traces</TabsTrigger>
            </TabsList>
            <TabsContent value="activity">
              <ActivityFeed events={events} workflow={workflow} />
            </TabsContent>
            <TabsContent value="traces">
              <TraceList runId={run.id} refreshKey={run.usage.llm_calls} />
            </TabsContent>
          </Tabs>
        </div>
      </div>
    </div>
  );
}

function Timeline({ run, workflow, events }: { run: RunDetail; workflow: Workflow; events: RunEvent[] }) {
  const flow = run.mode === "audit" ? AUDIT_FLOW : CONVERSION_FLOW;
  const steps = useMemo(() => Object.fromEntries(workflow.steps.map((s) => [s.id, s])), [workflow]);
  const gates = useMemo(() => Object.fromEntries(workflow.gates.map((g) => [g.id, g])), [workflow]);
  const completed = new Set(events.filter((e) => e.type === "step_completed").map((e) => e.step));
  const decided = new Set(run.approvals.filter((a) => a.decision === "approve").map((a) => a.gate));
  const services = run.options.services ?? [];
  const builtServices = new Set(
    events.filter((e) => e.type === "step_completed" && e.step === "build_service").map((e) => String(e.data.subject)),
  );

  function stateOf(id: string): ItemState {
    if (run.status === "waiting" && run.pending?.kind === "gate" && run.pending.gate === id) return "waiting";
    if (run.status === "waiting" && run.pending?.kind === "llm_unavailable" && run.pending.step === id)
      return "waiting";
    if (run.status === "running" && run.current_step === id) return "running";
    if (id.startsWith("gate")) return decided.has(id) ? "done" : "todo";
    if (id === "build_service")
      return services.length > 0 && services.every((s) => builtServices.has(s))
        ? "done"
        : completed.has(id)
          ? "running"
          : "todo";
    return completed.has(id) || run.status === "completed" ? "done" : "todo";
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Workflow</CardTitle>
        <CardDescription>
          {run.mode === "audit" ? "Mode B: steps 1–5, audit report, delivery." : "Mode A: all 10 steps."}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ol className="flex flex-col">
          {flow.map((id, i) => {
            const state = stateOf(id);
            const isGate = id.startsWith("gate");
            const label = isGate ? `Gate ${gates[id]?.number}: ${gates[id]?.title}` : steps[id]?.title;
            return (
              <li key={`${id}-${i}`} className={cn("flex items-start gap-3 py-1.5", isGate && "pl-6")}>
                <StateIcon state={state} gate={isGate} />
                <span className="flex flex-col">
                  <span className={cn("text-sm", state === "todo" ? "text-muted-foreground" : "font-medium")}>
                    {!isGate && steps[id]?.number ? `${steps[id].number}. ` : ""}
                    {label}
                  </span>
                  {!isGate && state !== "todo" && (
                    <span className="text-xs text-muted-foreground">{ROLE_LABEL[steps[id]?.role ?? ""]}</span>
                  )}
                  {id === "build_service" && services.length > 0 && (
                    <span className="text-xs text-muted-foreground">
                      {services.map((s) => `${s}${builtServices.has(s) ? " ✓" : ""}`).join(" · ")}
                    </span>
                  )}
                </span>
              </li>
            );
          })}
        </ol>
      </CardContent>
    </Card>
  );
}

function StateIcon({ state, gate }: { state: ItemState; gate: boolean }) {
  const label = { done: "Done", running: "In progress", waiting: "Waiting for you", todo: "Not started" }[state];
  const cls = "mt-0.5 size-4 shrink-0";
  const icon =
    state === "done" ? (
      <CheckCircle2 className={cn(cls, "text-success")} aria-hidden="true" />
    ) : state === "running" ? (
      <Loader2 className={cn(cls, "animate-spin text-brand")} aria-hidden="true" />
    ) : state === "waiting" ? (
      <PauseCircle className={cn(cls, "text-warning")} aria-hidden="true" />
    ) : gate ? (
      <ShieldCheck className={cn(cls, "text-muted-foreground")} aria-hidden="true" />
    ) : (
      <Circle className={cn(cls, "text-muted-foreground")} aria-hidden="true" />
    );
  return (
    <>
      {icon}
      <span className="sr-only">{label}:</span>
    </>
  );
}

function UsageCard({ run }: { run: RunDetail }) {
  const { usage } = run;
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>Budget used</CardTitle>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-3 gap-2 text-sm">
          <div>
            <dt className="text-xs text-muted-foreground">LLM calls</dt>
            <dd className="font-mono text-lg">{usage.llm_calls}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Tokens</dt>
            <dd className="font-mono text-lg">{(usage.prompt_tokens + usage.completion_tokens).toLocaleString()}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Model time</dt>
            <dd className="font-mono text-lg">{(usage.llm_time_ms / 1000).toFixed(1)}s</dd>
          </div>
        </dl>
      </CardContent>
    </Card>
  );
}

function describe(event: RunEvent, workflow: Workflow): string {
  const step = workflow.steps.find((s) => s.id === event.step);
  const role = ROLE_LABEL[String(event.data.role ?? step?.role ?? "")] ?? "";
  const subject = event.data.subject ? ` (${String(event.data.subject)})` : "";
  switch (event.type) {
    case "step_started":
      return `${role} started ${step?.title ?? event.step}${subject}`;
    case "step_completed":
      return `${role} finished ${step?.title ?? event.step}${subject}`;
    case "waiting":
      return event.data.kind === "gate"
        ? `Waiting for you at Gate ${String(event.data.number)}: ${String(event.data.title)}`
        : `Paused: the ${String(event.data.profile)} model server is unavailable`;
    case "answered":
      return `You answered: ${JSON.stringify(event.data.answer)}`;
    case "run_status":
      return `Run ${String(event.data.status)}`;
    case "llm_health":
      return `Model check (${String(event.data.profile)}): ${String(event.data.status)}`;
    case "llm_unavailable":
      return `Model server unreachable during ${event.step}`;
    case "resumed_after_restart":
      return "Resumed after an API restart";
    default:
      return event.type;
  }
}

function ActivityFeed({ events, workflow }: { events: RunEvent[]; workflow: Workflow }) {
  const recent = events.slice(-40).reverse();
  return (
    <Card size="sm">
      <CardContent>
        {recent.length === 0 ? (
          <p className="text-sm text-muted-foreground">No activity yet.</p>
        ) : (
          <ol className="flex flex-col gap-1.5" aria-live="polite">
            {recent.map((e) => (
              <li key={e.id} className="flex gap-3 text-sm">
                <time className="shrink-0 font-mono text-xs text-muted-foreground" dateTime={e.created_at}>
                  {new Date(e.created_at).toLocaleTimeString()}
                </time>
                <span>{describe(e, workflow)}</span>
              </li>
            ))}
          </ol>
        )}
      </CardContent>
    </Card>
  );
}

function TraceList({ runId, refreshKey }: { runId: string; refreshKey: number }) {
  const [traces, setTraces] = useState<Trace[] | null>(null);
  useEffect(() => {
    listTraces(runId)
      .then(setTraces)
      .catch(() => setTraces([]));
  }, [runId, refreshKey]);

  if (!traces) return <p className="text-sm text-muted-foreground">Loading…</p>;
  if (traces.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">No LLM calls in this run. Start a run with “One real LLM call”.</p>
    );
  }
  return (
    <ul className="flex flex-col gap-3">
      {traces.map((t) => (
        <li key={t.id}>
          <details className="rounded-lg border p-3 text-sm">
            <summary className="flex cursor-pointer flex-wrap items-center gap-2">
              <StatusBadge status={t.status} />
              <span className="font-medium">{t.name}</span>
              <span className="text-xs text-muted-foreground">
                {t.role} · {t.profile} · {t.prompt_tokens}+{t.completion_tokens} tokens ·{" "}
                {(t.latency_ms / 1000).toFixed(1)}s
              </span>
            </summary>
            <div className="mt-3 grid gap-2">
              {t.error && <p className="font-mono text-xs text-destructive">{t.error}</p>}
              <pre className="max-h-48 overflow-auto rounded bg-muted p-2 font-mono text-xs whitespace-pre-wrap">
                {JSON.stringify(t.input, null, 2)}
              </pre>
              {t.output && (
                <pre className="max-h-48 overflow-auto rounded bg-muted p-2 font-mono text-xs whitespace-pre-wrap">
                  {t.output}
                </pre>
              )}
            </div>
          </details>
        </li>
      ))}
    </ul>
  );
}
