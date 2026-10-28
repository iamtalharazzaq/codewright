"use client";

import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  Hammer,
  Loader2,
  Play,
  ScanSearch,
  Square,
  TestTube2,
  XCircle,
} from "lucide-react";

import { PreviewView } from "@/components/sandbox/preview-view";
import type { ActivityLog, LogStep } from "@/components/sandbox/use-sandbox";
import { useSandbox } from "@/components/sandbox/use-sandbox";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { SandboxAction, SandboxComponent, TestReport } from "@/lib/api";

const PACK_LABEL: Record<string, string> = {
  python: "Python",
  go: "Go",
  typescript: "TypeScript",
  javascript: "JavaScript",
  cpp: "C++",
};

const ACTIONS: { action: SandboxAction; label: string; icon: typeof Play }[] = [
  { action: "build", label: "Build", icon: Hammer },
  { action: "test", label: "Test", icon: TestTube2 },
  { action: "lint", label: "Lint", icon: ScanSearch },
  { action: "run", label: "Run", icon: Play },
];

/**
 * The project's sandbox (CODEWRIGHT.md Phase 5, ADR 0020): each component found by its Language Pack, with Build /
 * Test / Lint / Run in isolated containers, the live log, test results and the running previews.
 */
export function SandboxPanel({ projectId }: { projectId: string }) {
  const sb = useSandbox(projectId);
  const runner = sb.status?.runner;
  const down = runner && (runner.error || !runner.docker || !runner.gateway);
  const missing = Object.entries(runner?.images ?? {})
    .filter(([, ok]) => !ok)
    .map(([k]) => k);
  const runnable = sb.status?.components.some((c) => c.run) ?? false;

  return (
    <div className="flex flex-col gap-4">
      {down && (
        <p
          role="alert"
          className="flex items-start gap-2 rounded-lg border border-destructive/40 p-3 text-sm text-destructive"
        >
          <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          {runner.error ?? "The sandbox runner can't reach Docker or its gateway."} Start it with{" "}
          <code>docker compose up -d sandbox-runner</code>.
        </p>
      )}
      {missing.length > 0 && (
        <p role="alert" className="text-sm text-destructive">
          Missing toolchain images: {missing.join(", ")}. Build them with <code>make sandbox-images</code>.
        </p>
      )}
      {sb.error && (
        <p role="alert" className="text-sm text-destructive">
          {sb.error}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {ACTIONS.map(({ action, label, icon: Icon }) => (
          <Button
            key={action}
            size="sm"
            variant={action === "run" ? "default" : "outline"}
            disabled={sb.busy || !sb.status?.components.length || (action === "run" && !runnable)}
            onClick={() => void sb.start(action)}
          >
            <Icon aria-hidden="true" />
            {label} {action === "run" ? "app" : "all"}
          </Button>
        ))}
        {(sb.previews.length > 0 || (sb.status?.session?.services.length ?? 0) > 0) && (
          <Button size="sm" variant="ghost" onClick={() => void sb.stopAll()}>
            <Square aria-hidden="true" />
            Stop everything
          </Button>
        )}
      </div>

      {sb.status && sb.status.components.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No buildable Python, Go, TypeScript, JavaScript or C++ project found (go.mod, pyproject.toml, package.json,
          CMakeLists.txt…).
        </p>
      )}
      <ul className="flex flex-col gap-2">
        {sb.status?.components.map((c) => (
          <ComponentRow key={`${c.pack}:${c.path}`} component={c} busy={sb.busy} onAction={sb.start} />
        ))}
      </ul>

      {sb.log && <ActivityView log={sb.log} />}

      {sb.previews.length > 0 && (
        <div className="flex h-[32rem] flex-col gap-2">
          <h3 className="text-sm font-medium">Preview</h3>
          <PreviewView projectId={projectId} previews={sb.previews} onStop={sb.stopOne} />
        </div>
      )}
    </div>
  );
}

function ComponentRow({
  component: c,
  busy,
  onAction,
}: {
  component: SandboxComponent;
  busy: boolean;
  onAction: (a: SandboxAction, paths: string[]) => Promise<void>;
}) {
  return (
    <li className="flex flex-wrap items-center gap-2 rounded-lg border p-2 text-sm">
      <Badge variant="secondary">{PACK_LABEL[c.pack] ?? c.pack}</Badge>
      <code className="font-mono text-xs">{c.path === "." ? "(root)" : c.path}</code>
      <span className="text-muted-foreground">{c.kind}</span>
      {c.frameworks.length > 0 && (
        <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">{c.frameworks.join(" · ")}</span>
      )}
      <span className="ml-auto flex gap-1">
        {ACTIONS.filter((a) => a.action !== "run" || c.run).map(({ action, label, icon: Icon }) => (
          <Button
            key={action}
            size="icon-xs"
            variant="ghost"
            disabled={busy}
            title={`${label} ${c.path}${action === "run" && c.run ? ` (${c.run.kind} preview)` : ""}`}
            aria-label={`${label} ${c.path === "." ? "root" : c.path}`}
            onClick={() => void onAction(action, [c.path])}
          >
            <Icon aria-hidden="true" />
          </Button>
        ))}
      </span>
    </li>
  );
}

function ActivityView({ log }: { log: ActivityLog }) {
  const { status } = log;
  return (
    <section aria-label="Sandbox activity" className="flex flex-col gap-2">
      <h3 className="flex items-center gap-2 text-sm font-medium">
        {status === "running" ? (
          <Loader2 className="size-4 animate-spin" aria-hidden="true" />
        ) : status === "passed" ? (
          <CheckCircle2 className="size-4 text-emerald-600 dark:text-emerald-400" aria-hidden="true" />
        ) : (
          <XCircle className="size-4 text-destructive" aria-hidden="true" />
        )}
        <span className="capitalize">{log.activity.action}</span>
        <span className="font-normal text-muted-foreground">
          {log.activity.components.map((p) => (p === "." ? "(root)" : p)).join(", ")} · {status}
        </span>
      </h3>
      {log.error && (
        <p role="alert" className="text-sm text-destructive">
          {log.error}
        </p>
      )}
      {log.notes.map((n, i) => (
        <p key={i} className="text-xs text-muted-foreground">
          {n}
        </p>
      ))}
      <ol className="flex flex-col gap-1">
        {log.steps.map((s) => (
          <StepView key={s.key} step={s} />
        ))}
      </ol>
      {log.reports.map((r, i) => (
        <ReportView key={i} component={r.component} report={r.report} />
      ))}
    </section>
  );
}

function StepView({ step }: { step: LogStep }) {
  return (
    <li>
      <details open={step.status === "failed" || step.status === "running"} className="group rounded-md border">
        <summary className="flex cursor-pointer list-none items-center gap-2 px-2 py-1.5 text-sm">
          <ChevronRight className="size-3.5 transition-transform group-open:rotate-90" aria-hidden="true" />
          {step.status === "running" ? (
            <Loader2 className="size-3.5 animate-spin" aria-label="running" />
          ) : step.status === "ok" ? (
            <CheckCircle2 className="size-3.5 text-emerald-600 dark:text-emerald-400" aria-label="passed" />
          ) : (
            <XCircle className="size-3.5 text-destructive" aria-label="failed" />
          )}
          <span className="font-medium">{step.name}</span>
          <code className="min-w-0 flex-1 truncate text-xs text-muted-foreground">{step.cmd.join(" ")}</code>
          {step.network === "none" && <span className="text-xs text-muted-foreground">offline</span>}
          {step.duration !== undefined && <span className="text-xs text-muted-foreground">{step.duration}s</span>}
        </summary>
        {step.output && (
          <pre className="max-h-72 overflow-auto border-t bg-muted/40 p-2 font-mono text-xs whitespace-pre-wrap">
            {step.output}
          </pre>
        )}
      </details>
    </li>
  );
}

function ReportView({ component, report }: { component: string; report: TestReport }) {
  const failures = report.cases.filter((c) => c.status === "failed" || c.status === "error");
  return (
    <div className="rounded-md border p-2 text-sm">
      <p className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="font-medium">
          Tests{component !== "." && ` · ${component}`} ({report.tool})
        </span>
        {report.found ? (
          <>
            <span className="text-emerald-700 dark:text-emerald-400">{report.passed} passed</span>
            <span className={report.failed ? "text-destructive" : "text-muted-foreground"}>{report.failed} failed</span>
            {report.errors > 0 && <span className="text-destructive">{report.errors} errors</span>}
            {report.skipped > 0 && <span className="text-muted-foreground">{report.skipped} skipped</span>}
          </>
        ) : (
          <span className="text-muted-foreground">no test report was written</span>
        )}
      </p>
      {failures.length > 0 && (
        <ul className="mt-2 flex flex-col gap-1">
          {failures.slice(0, 20).map((f) => (
            <li key={f.name}>
              <details>
                <summary className="cursor-pointer font-mono text-xs text-destructive">{f.name}</summary>
                <pre className="mt-1 max-h-48 overflow-auto rounded bg-muted/40 p-2 font-mono text-xs whitespace-pre-wrap">
                  {f.message}
                </pre>
              </details>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
