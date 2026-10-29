"use client";

import {
  Ban,
  CheckCircle2,
  Circle,
  CircleDot,
  FileText,
  Loader2,
  PauseCircle,
  ShieldCheck,
  Wifi,
  WifiOff,
  XCircle,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { BudgetCard, GateCard, LLMUnavailableCard } from "@/components/runs/pending-card";
import { runTitle } from "@/components/runs/runs-view";
import { useRunEvents } from "@/components/runs/use-run-events";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  cancelRun,
  getPlaybook,
  getRun,
  listTraces,
  PROFILE_LABEL,
  type Playbook,
  type RunDetail,
  type RunEvent,
  type Trace,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const ROLE_LABEL: Record<string, string> = {
  project_manager: "Project Manager",
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

type ItemState = "done" | "failed" | "running" | "waiting" | "todo";

function unknownPlaybook(name: string): Playbook {
  return {
    name,
    title: name,
    description: "This playbook is no longer available; the run's history is shown as recorded.",
    intent: null,
    lead_role: "project_manager",
    tier: 0,
    steps: [],
    gates: [],
    inputs_schema: {},
  };
}

export function RunView({ runId }: { runId: string }) {
  const [run, setRun] = useState<RunDetail | null>(null);
  const [playbook, setPlaybook] = useState<Playbook | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { events, connected, live } = useRunEvents(runId);

  const refresh = useCallback(() => {
    getRun(runId)
      .then(setRun)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, [runId]);

  const playbookName = run?.playbook;
  useEffect(() => {
    if (!playbookName) return;
    // A run whose playbook was removed or renamed still opens, with a plain step list.
    getPlaybook(playbookName)
      .then(setPlaybook)
      .catch(() => setPlaybook(unknownPlaybook(playbookName)));
  }, [playbookName]);

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
  if (!run || !playbook) {
    return (
      <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" aria-hidden="true" /> Loading run…
      </p>
    );
  }

  const active = run.status === "running" || run.status === "waiting" || run.status === "created";
  // A step's own "failed" status always outranks the run-level status badge: a run that reached "completed" or
  // "waiting" (at the approval gate) must still read as broken if a verify/test/lint step did not pass.
  const hasFailedStep = Object.values(run.steps).some((s) => s.status === "failed");

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex flex-col gap-1">
          <h1 className="font-heading text-2xl font-semibold tracking-tight">{runTitle(run)}</h1>
          <p className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            <span className="font-mono">{run.id.slice(0, 8)}</span>
            <StatusBadge
              status={hasFailedStep ? "failed" : run.status}
              label={hasFailedStep ? `${run.status.replaceAll("_", " ")} · a step failed` : undefined}
            />
            <span>
              {playbook.title} · tier {run.tier}
            </span>
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
        <GateCard
          key={JSON.stringify(run.pending)}
          runId={run.id}
          prompt={run.pending}
          onAnswered={refresh}
          hasFailedStep={hasFailedStep}
        />
      )}
      {run.status === "waiting" && run.pending?.kind === "llm_unavailable" && (
        <LLMUnavailableCard runId={run.id} prompt={run.pending} onAnswered={refresh} />
      )}
      {run.status === "waiting" && run.pending?.kind === "budget_exceeded" && (
        <BudgetCard runId={run.id} prompt={run.pending} onAnswered={refresh} />
      )}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div className="flex flex-col gap-6">
          <Timeline run={run} playbook={playbook} events={events} />
          <ServiceBoard run={run} />
          <PlanCard run={run} />
          {run.artifacts.length > 0 && <ArtifactsCard run={run} />}
        </div>
        <div className="flex flex-col gap-6">
          <UsageCard run={run} />
          {(live || run.status === "running") && <LiveOutput live={live} />}
          <Tabs defaultValue="activity">
            <TabsList>
              <TabsTrigger value="activity">Activity</TabsTrigger>
              <TabsTrigger value="traces">LLM traces</TabsTrigger>
            </TabsList>
            <TabsContent value="activity">
              <ActivityFeed events={events} playbook={playbook} />
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

const SERVICE_STATUS: Record<string, { label: string; tone: string }> = {
  extracted: { label: "Extracted", tone: "text-emerald-600" },
  scaffolded: { label: "Scaffolded, code not moved", tone: "text-amber-600" },
  blocked: { label: "Not extracted", tone: "text-amber-600" },
  undone: { label: "Undone (tests or replay failed)", tone: "text-red-600" },
  skipped: { label: "Skipped", tone: "text-muted-foreground" },
};

/** One row per service of a microservices conversion, from the `build_service:<name>` results: its status and the
 *  reason when it was not extracted or was undone (the step summary reads "<name>: <status> (<reason>)"). */
function ServiceBoard({ run }: { run: RunDetail }) {
  const rows = Object.entries(run.steps)
    .filter(([k]) => k.startsWith("build_service:"))
    .map(([k, v]) => {
      const name = k.slice("build_service:".length);
      const rest = (v.summary ?? "").replace(`${name}: `, "");
      const [status] = rest.split(" ");
      const reason = rest.includes("(") ? rest.slice(rest.indexOf("(") + 1).replace(/\)$/, "") : "";
      return { name, status, reason };
    });
  if (rows.length === 0) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Services</CardTitle>
        <CardDescription>
          Nothing here is deployed. Replay results and the cut-over steps are in the approval card and the report.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="flex flex-col gap-2">
          {rows.map((r) => {
            const s = SERVICE_STATUS[r.status] ?? { label: r.status, tone: "text-muted-foreground" };
            return (
              <li key={r.name} className="flex flex-col text-sm">
                <span className="flex items-center justify-between gap-3">
                  <span className="font-medium">{r.name}</span>
                  <span className={cn("text-xs", s.tone)}>{s.label}</span>
                </span>
                {r.reason && <span className="text-xs text-muted-foreground">{r.reason}</span>}
              </li>
            );
          })}
        </ul>
      </CardContent>
    </Card>
  );
}

function Timeline({ run, playbook, events }: { run: RunDetail; playbook: Playbook; events: RunEvent[] }) {
  const steps = useMemo(() => Object.fromEntries(playbook.steps.map((s) => [s.id, s])), [playbook]);
  const gates = useMemo(() => Object.fromEntries(playbook.gates.map((g) => [g.id, g])), [playbook]);
  const completed = new Set(events.filter((e) => e.type === "step_completed").map((e) => e.step));
  const decided = new Set(run.approvals.filter((a) => a.decision === "approve").map((a) => a.gate));
  // Steps that run once per subject (e.g. one build per service) record results as "<step>:<subject>".
  const subjects = (id: string) =>
    Object.keys(run.steps)
      .filter((k) => k.startsWith(`${id}:`))
      .map((k) => k.slice(id.length + 1));
  const plannedSubjects = Array.isArray(run.inputs.services) ? (run.inputs.services as string[]) : [];

  function stateOf(id: string): ItemState {
    const p = run.pending;
    if (run.status === "waiting" && p?.kind === "gate" && p.gate === id) return "waiting";
    if (run.status === "waiting" && p && p.kind !== "gate" && p.step === id) return "waiting";
    if (run.status === "running" && run.current_step === id) return "running";
    if (gates[id]) return decided.has(id) ? "done" : "todo";
    const done = subjects(id);
    if (done.length > 0 && plannedSubjects.length > 0)
      return plannedSubjects.every((s) => done.includes(s)) ? "done" : "running";
    // A step's own recorded outcome always wins: a run reaching "completed" never repaints a failed step green.
    if (run.steps[id]?.status === "failed") return "failed";
    return completed.has(id) || run.steps[id]?.status === "done" || run.status === "completed" ? "done" : "todo";
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Timeline</CardTitle>
        <CardDescription>{playbook.description}</CardDescription>
      </CardHeader>
      <CardContent>
        <ol className="flex flex-col">
          {run.flow.map((id, i) => {
            const state = stateOf(id);
            const gate = gates[id];
            const step = steps[id];
            const label = gate
              ? gate.number != null
                ? `Gate ${gate.number}: ${gate.title}`
                : gate.title
              : `${step?.number ? `${step.number}. ` : ""}${step?.title ?? id}`;
            const done = subjects(id);
            return (
              <li key={`${id}-${i}`} className={cn("flex items-start gap-3 py-1.5", gate && "pl-6")}>
                <StateIcon state={state} gate={Boolean(gate)} />
                <span className="flex flex-col">
                  <span
                    className={cn(
                      "text-sm",
                      state === "todo" ? "text-muted-foreground" : "font-medium",
                      state === "failed" && "text-destructive",
                    )}
                  >
                    {label}
                  </span>
                  {step && state !== "todo" && (
                    <span className="text-xs text-muted-foreground">
                      {ROLE_LABEL[step.role] ?? step.role}
                      {run.steps[id]?.summary ? ` · ${run.steps[id].summary}` : ""}
                    </span>
                  )}
                  {done.length > 0 && (
                    <span className="text-xs text-muted-foreground">
                      {(plannedSubjects.length ? plannedSubjects : done)
                        .map((s) => `${s}${done.includes(s) ? " ✓" : ""}`)
                        .join(" · ")}
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

function PlanCard({ run }: { run: RunDetail }) {
  if (run.plan.length === 0) return null;
  const done = run.plan.filter((p) => p.status === "done").length;
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>
          Plan{" "}
          <span className="font-mono text-sm text-muted-foreground">
            {done}/{run.plan.length}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ul className="flex flex-col gap-1.5">
          {run.plan.map((item) => (
            <li key={item.id} className="flex items-start gap-2 text-sm">
              {item.status === "done" ? (
                <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" aria-hidden="true" />
              ) : item.status === "failed" ? (
                <XCircle className="mt-0.5 size-4 shrink-0 text-destructive" aria-hidden="true" />
              ) : item.status === "in_progress" ? (
                <CircleDot className="mt-0.5 size-4 shrink-0 text-brand" aria-hidden="true" />
              ) : (
                <Circle className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
              )}
              <span className="sr-only">{item.status.replace("_", " ")}:</span>
              <span
                className={cn(
                  item.status === "done" && "text-muted-foreground line-through",
                  item.status === "failed" && "font-medium text-destructive",
                )}
              >
                {item.title}
              </span>
              <span className="ml-auto text-xs text-muted-foreground">{ROLE_LABEL[item.role] ?? item.role}</span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

function ArtifactsCard({ run }: { run: RunDetail }) {
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>Artifacts</CardTitle>
        <CardDescription>Files in the run workspace (opened in the side panel from Phase 2).</CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="flex flex-col gap-1.5">
          {run.artifacts.map((a, i) => (
            <li key={`${a.path}-${i}`} className="flex items-center gap-2 text-sm">
              <FileText className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
              <span className="font-medium">{a.title}</span>
              <span className="font-mono text-xs text-muted-foreground">{a.path}</span>
              <span className="ml-auto text-xs text-muted-foreground">{a.kind}</span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

function LiveOutput({ live }: { live: { agent: string; text: string } | null }) {
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          Live output
          {live && <span className="text-xs font-normal text-muted-foreground">{live.agent}</span>}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {live ? (
          <pre
            className="max-h-64 overflow-auto rounded bg-muted p-2 font-mono text-xs whitespace-pre-wrap"
            aria-live="off"
          >
            {live.text}
          </pre>
        ) : (
          <p className="text-sm text-muted-foreground">Waiting for the model…</p>
        )}
      </CardContent>
    </Card>
  );
}

function StateIcon({ state, gate }: { state: ItemState; gate: boolean }) {
  const label = {
    done: "Done",
    failed: "Failed",
    running: "In progress",
    waiting: "Waiting for you",
    todo: "Not started",
  }[state];
  const cls = "mt-0.5 size-4 shrink-0";
  const icon =
    state === "done" ? (
      <CheckCircle2 className={cn(cls, "text-success")} aria-hidden="true" />
    ) : state === "failed" ? (
      <XCircle className={cn(cls, "text-destructive")} aria-hidden="true" />
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

function describe(event: RunEvent, playbook: Playbook): string {
  const step = playbook.steps.find((s) => s.id === event.step);
  const role = ROLE_LABEL[String(event.data.role ?? step?.role ?? "")] ?? "";
  const subject = event.data.subject ? ` (${String(event.data.subject)})` : "";
  switch (event.type) {
    case "step_started":
      return `${role} started ${step?.title ?? event.step}${subject}`;
    case "step_completed":
      return `${role} finished ${step?.title ?? event.step}${subject}`;
    case "waiting":
      if (event.data.kind === "gate")
        return `Waiting for you at ${event.data.number != null ? `Gate ${String(event.data.number)}: ` : ""}${String(event.data.title)}`;
      if (event.data.kind === "budget_exceeded") return `Paused: budget reached (${String(event.data.reason)})`;
      return `Paused: the ${String(event.data.profile)} model server is unavailable`;
    case "plan_updated":
      return "Plan updated";
    case "agent_activity": {
      const agent = String(event.data.agent);
      if (Array.isArray(event.data.tool_calls))
        return `${agent}: ${(event.data.tool_calls as Array<{ name: string; target?: string | null }>)
          .map((c) => (c.target ? `${c.name} → ${c.target}` : c.name))
          .join(", ")}`;
      return `${agent}: ${String(event.data.tool_result)} ${event.data.status === "error" ? "failed" : "done"}`;
    }
    case "answered": {
      const answer = event.data.answer as string | { decision: string; comment?: string };
      if (typeof answer === "string") return `You chose: ${answer.replaceAll("_", " ")}`;
      return `You chose ${answer.decision}${answer.comment ? `: “${answer.comment}”` : ""}`;
    }
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

function ActivityFeed({ events, playbook }: { events: RunEvent[]; playbook: Playbook }) {
  const recent = events
    .filter((e) => e.type !== "plan_updated")
    .slice(-60)
    .reverse();
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
                <span>{describe(e, playbook)}</span>
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
    return <p className="text-sm text-muted-foreground">No LLM calls in this run yet.</p>;
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
