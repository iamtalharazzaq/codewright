"use client";

import {
  Camera,
  CheckCircle2,
  ChevronRight,
  CircleDot,
  Gauge,
  Globe,
  Loader2,
  PenLine,
  Radio,
  Repeat,
  Square,
  TestTube2,
  Upload,
  XCircle,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { useVerification, type LiveActivity } from "@/components/tests/use-verification";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  getVerificationReport,
  importHar,
  screenshotUrl,
  setNoiseRules,
  stopRecorder,
  type BenchDelta,
  type BenchReport,
  type Difference,
  type NoiseRule,
  type ReplayReport,
  type ReportSummary,
  type ScreensReport,
  type TestsReport,
  type VerifyAction,
} from "@/lib/api";

const ACTIONS: { action: VerifyAction; label: string; icon: typeof Radio; hint: string }[] = [
  { action: "test", label: "Run tests", icon: TestTube2, hint: "Every component's tests, with coverage" },
  { action: "record", label: "Record", icon: Radio, hint: "Reset the app, send the journeys, then replay once" },
  { action: "replay", label: "Replay", icon: Repeat, hint: "Reset the app and compare it with the last recording" },
  { action: "characterize", label: "Write journeys", icon: PenLine, hint: "The QA sub-agent writes the requests" },
  {
    action: "bench",
    label: "Benchmark",
    icon: Gauge,
    hint: "k6 load on the recording's reads, compared with last time",
  },
  {
    action: "screens",
    label: "Screenshots",
    icon: Camera,
    hint: "Every page in a browser, compared with accepted shots",
  },
  { action: "record-live", label: "Record in browser", icon: Globe, hint: "Use the app through a recorder, then stop" },
];

const time = (t: number) => new Date(t * 1000).toLocaleString();

/**
 * The Tests tab (CODEWRIGHT.md Section 2.2, Phase 7): the latest test run with coverage, the latest replay with every
 * difference and why it does or doesn't count, the recordings, and the noise rules, which the user can switch.
 */
export function TestsTab({ projectId }: { projectId: string }) {
  const v = useVerification(projectId);
  const reports = v.status?.reports ?? [];
  const latestTests = reports.find((r) => r.kind === "tests");
  const latestReplay = reports.find((r) => r.kind === "replay");
  const latestBench = reports.find((r) => r.kind === "bench");
  const latestScreens = reports.find((r) => r.kind === "screens");
  const har = useRef<HTMLInputElement>(null);
  const [harError, setHarError] = useState<string | null>(null);
  const upload = async (file: File | undefined) => {
    if (!file) return;
    try {
      await importHar(projectId, JSON.parse(await file.text()));
      setHarError(null);
      void v.reload();
    } catch (e) {
      setHarError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col gap-4 overflow-y-auto p-4">
      <div className="flex flex-wrap gap-2">
        {ACTIONS.map(({ action, label, icon: Icon, hint }) => (
          <Button
            key={action}
            size="sm"
            variant={action === "replay" ? "default" : "outline"}
            disabled={v.busy}
            title={hint}
            onClick={() => void v.start(action)}
          >
            <Icon aria-hidden="true" />
            {label}
          </Button>
        ))}
        <Button
          size="sm"
          variant="ghost"
          title="A HAR file saved from the browser's developer tools"
          onClick={() => har.current?.click()}
        >
          <Upload aria-hidden="true" />
          Import HAR
        </Button>
        <input
          ref={har}
          type="file"
          accept=".har,application/json"
          className="hidden"
          aria-label="HAR file"
          onChange={(e) => {
            void upload(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
      </div>
      {harError && (
        <p role="alert" className="text-sm text-destructive">
          {harError}
        </p>
      )}
      {v.error && (
        <p role="alert" className="text-sm text-destructive">
          {v.error}
        </p>
      )}
      {v.live && <Live live={v.live} projectId={projectId} />}
      {latestTests && <TestsSection projectId={projectId} summary={latestTests} />}
      {latestReplay && <ReplaySection projectId={projectId} summary={latestReplay} rules={v.status?.rules ?? []} />}
      {latestBench && <BenchSection projectId={projectId} summary={latestBench} />}
      {latestScreens && (
        <ScreensSection
          projectId={projectId}
          summary={latestScreens}
          busy={v.busy}
          onAccept={() => void v.start("screens", { accept: true })}
        />
      )}
      {!latestTests && !latestReplay && !v.live && (
        <p className="text-sm text-muted-foreground">
          Run the tests, or record the app&apos;s traffic: Codewright starts the app in the sandbox, sends the journeys
          and replays them on a fresh start to prove the recording is stable. Later changes are replayed against it.
        </p>
      )}
      {v.status && v.status.journeys.length > 0 && (
        <Section title="Journeys">
          <ul className="text-sm">
            {v.status.journeys.map((j, i) => (
              <li key={`${j.name}-${i}`} className="flex justify-between gap-2 py-0.5">
                <span>{j.name}</span>
                <span className="text-muted-foreground">
                  {j.steps} requests · {j.source}
                </span>
              </li>
            ))}
          </ul>
        </Section>
      )}
      {v.status && v.status.recordings.length > 0 && (
        <Section title="Recordings">
          <ul className="text-sm">
            {v.status.recordings.slice(0, 5).map((r) => (
              <li key={r.id} className="flex justify-between gap-2 py-0.5">
                <span className="truncate font-mono text-xs">{r.id}</span>
                <span className="shrink-0 text-muted-foreground">
                  {r.source} · {r.exchanges} requests, {r.endpoints} endpoints
                  {r.server_errors ? `, ${r.server_errors} server errors` : ""}
                </span>
              </li>
            ))}
          </ul>
        </Section>
      )}
      {v.status && <NoiseRules projectId={projectId} rules={v.status.rules} onSaved={() => void v.reload()} />}
    </div>
  );
}

function Section({ title, children, right }: { title: string; children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-2 rounded-lg border p-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-medium">{title}</h3>
        {right}
      </div>
      {children}
    </section>
  );
}

function Verdict({ ok, label }: { ok: boolean; label: string }) {
  return ok ? (
    <Badge variant="secondary" className="gap-1">
      <CheckCircle2 className="size-3" aria-hidden="true" />
      {label}
    </Badge>
  ) : (
    <Badge variant="destructive" className="gap-1">
      <XCircle className="size-3" aria-hidden="true" />
      {label}
    </Badge>
  );
}

function Live({ live, projectId }: { live: LiveActivity; projectId: string }) {
  const running = live.status === "running";
  return (
    <Section
      title={`${ACTIONS.find((a) => a.action === live.activity.action)?.label ?? live.activity.action}: ${live.activity.components.join(", ")}`}
      right={
        running ? (
          <Loader2 className="size-4 animate-spin text-muted-foreground" aria-label="Running" />
        ) : (
          <Verdict ok={live.status === "passed"} label={live.status} />
        )
      }
    >
      {running && live.recorderUrl && (
        <div className="flex flex-wrap items-center gap-2 rounded bg-primary/5 p-2 text-sm">
          <span>Recording: use the app at</span>
          <a href={live.recorderUrl} target="_blank" rel="noreferrer" className="font-mono underline">
            {live.recorderUrl}
          </a>
          <Button size="sm" variant="destructive" className="ml-auto" onClick={() => void stopRecorder(projectId)}>
            <Square aria-hidden="true" />
            Stop and save
          </Button>
        </div>
      )}
      <div
        role="log"
        aria-live="polite"
        className="max-h-48 overflow-y-auto rounded bg-muted/50 p-2 font-mono text-xs leading-relaxed"
      >
        {live.lines.length === 0 && <p className="text-muted-foreground">Starting…</p>}
        {live.lines.map((l) => (
          <p
            key={l.key}
            className={l.tone === "bad" ? "text-destructive" : l.tone === "muted" ? "text-muted-foreground" : undefined}
          >
            {l.text}
          </p>
        ))}
      </div>
      {live.error && !running && <p className="text-sm text-destructive">{live.error}</p>}
    </Section>
  );
}

function useReport<T extends ReportSummary>(projectId: string, id: string) {
  const [report, setReport] = useState<T | null>(null);
  useEffect(() => {
    let cancelled = false;
    getVerificationReport<T>(projectId, id)
      .then((r) => !cancelled && setReport(r))
      .catch(() => !cancelled && setReport(null));
    return () => {
      cancelled = true;
    };
  }, [projectId, id]);
  return report;
}

function TestsSection({ projectId, summary }: { projectId: string; summary: ReportSummary }) {
  const report = useReport<TestsReport>(projectId, summary.id);
  const s = summary.summary;
  const bad = (s?.failed ?? 0) + (s?.errors ?? 0);
  return (
    <Section
      title="Tests"
      right={<Verdict ok={summary.ok} label={s ? `${s.passed ?? 0} passed${bad ? `, ${bad} failed` : ""}` : "tests"} />}
    >
      <p className="text-xs text-muted-foreground">
        {time(summary.started_at)}
        {s?.coverage != null && ` · coverage ${s.coverage}%`}
      </p>
      {report?.components.map((c) => {
        const r = "tool" in c.report ? c.report : null;
        const failed = r?.cases.filter((x) => x.status === "failed" || x.status === "error") ?? [];
        return (
          <div key={c.path} className="flex flex-col gap-1 text-sm">
            <div className="flex items-center justify-between gap-2">
              <span>
                <code>{c.path}</code> <span className="text-muted-foreground">{r?.tool ?? c.pack}</span>
              </span>
              <span className={c.ok ? "text-muted-foreground" : "text-destructive"}>
                {r ? `${r.passed}/${r.total}` : (c.error ?? (c.failed_step ? `${c.failed_step} failed` : "no tests"))}
              </span>
            </div>
            {r?.coverage && <CoverageBar percent={r.coverage.percent} label={`${r.coverage.tool}`} />}
            {failed.slice(0, 5).map((x) => (
              <details key={x.name} className="rounded bg-destructive/5 px-2 py-1 text-xs">
                <summary className="cursor-pointer text-destructive">{x.name}</summary>
                <pre className="mt-1 whitespace-pre-wrap">{x.message.slice(0, 1500)}</pre>
              </details>
            ))}
          </div>
        );
      })}
    </Section>
  );
}

function CoverageBar({ percent, label }: { percent: number; label: string }) {
  return (
    <div className="flex items-center gap-2 text-xs text-muted-foreground">
      <div
        className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted"
        role="meter"
        aria-label={`Coverage (${label})`}
        aria-valuenow={percent}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div className="h-full rounded-full bg-primary" style={{ width: `${Math.min(100, percent)}%` }} />
      </div>
      <span className="w-20 text-right">{percent}% lines</span>
    </div>
  );
}

function ReplaySection({
  projectId,
  summary,
  rules,
}: {
  projectId: string;
  summary: ReportSummary;
  rules: NoiseRule[];
}) {
  const report = useReport<ReplayReport>(projectId, summary.id);
  const [onlyChanged, setOnlyChanged] = useState(true);
  const c = summary.counts;
  const described = useMemo(() => new Map(rules.map((r) => [r.id, r.description])), [rules]);
  const rows = (report?.results ?? []).filter((r) => !onlyChanged || r.differences.length > 0 || r.error);
  return (
    <Section title="Replay" right={<Verdict ok={summary.ok} label={c ? `${c.regression} regressions` : "replay"} />}>
      <p className="text-xs text-muted-foreground">
        {time(summary.started_at)} · {summary.target?.component ?? ""} · recording{" "}
        <span className="font-mono">{summary.recording}</span>
      </p>
      {c && (
        <div className="grid grid-cols-4 gap-2 text-center text-xs">
          <Count label="requests" value={c.exchanges} />
          <Count label="identical" value={c.identical} />
          <Count label="noise" value={c.noise} />
          <Count label="regressions" value={c.regression} bad={c.regression > 0} />
        </div>
      )}
      {summary.noise_used && Object.keys(summary.noise_used).length > 0 && (
        <div className="text-xs">
          <p className="pb-1 text-muted-foreground">Ignored as noise:</p>
          <ul className="flex flex-col gap-1">
            {Object.entries(summary.noise_used).map(([rule, n]) => (
              <li key={rule} title={described.get(rule)}>
                <Badge variant="outline">{rule}</Badge> {n}×{" "}
                <span className="text-muted-foreground">{described.get(rule)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <label className="flex items-center gap-2 text-xs">
        <Checkbox checked={onlyChanged} onCheckedChange={(v) => setOnlyChanged(Boolean(v))} />
        Only requests with differences
      </label>
      <ul className="flex flex-col gap-1 text-xs">
        {rows.slice(0, 200).map((r) => (
          <li key={r.seq}>
            <details className="rounded border px-2 py-1">
              <summary className="flex cursor-pointer items-center gap-2">
                <ChevronRight className="size-3 shrink-0" aria-hidden="true" />
                {r.regressions > 0 ? (
                  <XCircle className="size-3 shrink-0 text-destructive" aria-label="Regression" />
                ) : (
                  <CircleDot className="size-3 shrink-0 text-muted-foreground" aria-label="No regression" />
                )}
                <span className="truncate font-mono">
                  {r.method} {r.path}
                </span>
                <span className="ml-auto shrink-0 text-muted-foreground">
                  {r.status_before ?? "–"} → {r.status_after ?? "–"}
                </span>
              </summary>
              <p className="py-1 text-muted-foreground">
                {r.journey} · {r.step}
                {r.error && <span className="text-destructive"> · {r.error}</span>}
              </p>
              {r.differences.length > 0 && <Differences items={r.differences} />}
            </details>
          </li>
        ))}
        {rows.length === 0 && <li className="text-muted-foreground">Every answer matched the recording.</li>}
      </ul>
    </Section>
  );
}

const ms = (v: number | null | undefined) => (v == null ? "–" : `${v} ms`);
const change = (d: BenchDelta | undefined, lowerIsBetter = true) => {
  if (!d || d.change_pct == null) return null;
  const worse = lowerIsBetter ? d.change_pct > 10 : d.change_pct < -10;
  return (
    <span className={worse ? "text-destructive" : "text-muted-foreground"}>
      {" "}
      ({d.change_pct > 0 ? "+" : ""}
      {d.change_pct}%)
    </span>
  );
};

function BenchSection({ projectId, summary }: { projectId: string; summary: ReportSummary }) {
  const report = useReport<BenchReport>(projectId, summary.id);
  const s = report?.summary;
  const cmp = summary.comparison;
  const before = new Map((cmp?.endpoints ?? []).map((e) => [e.endpoint, e]));
  return (
    <Section title="Benchmark" right={<Verdict ok={summary.ok} label={s ? `p95 ${ms(s.p95_ms)}` : "k6"} />}>
      <p className="text-xs text-muted-foreground">
        {time(summary.started_at)} · k6 {report ? `${report.settings.vus} users, ${report.settings.duration_s} s` : ""}
        {report?.compared_with && ` · compared with ${report.compared_with}`}
      </p>
      {s && (
        <div className="grid grid-cols-4 gap-2 text-center text-xs">
          <Count label="requests" value={s.requests} />
          <div className="rounded bg-muted/50 py-1">
            <div className="text-base font-medium">{s.rps}</div>
            <div className="text-muted-foreground">req/s{change(cmp?.rps, false)}</div>
          </div>
          <div className="rounded bg-muted/50 py-1">
            <div className="text-base font-medium">{ms(s.p95_ms)}</div>
            <div className="text-muted-foreground">p95{change(cmp?.p95_ms)}</div>
          </div>
          <Count label="failed %" value={Math.round(s.failed_rate * 1000) / 10} bad={s.failed_rate > 0} />
        </div>
      )}
      <table className="w-full table-fixed text-left text-xs">
        <thead className="text-muted-foreground">
          <tr>
            <th className="w-1/2 font-normal">Endpoint</th>
            <th className="font-normal">avg</th>
            <th className="font-normal">p95</th>
            <th className="font-normal">max</th>
          </tr>
        </thead>
        <tbody>
          {s?.endpoints.map((e) => (
            <tr key={e.endpoint}>
              <td className="truncate font-mono" title={e.endpoint}>
                {e.endpoint}
              </td>
              <td>{ms(e.avg_ms)}</td>
              <td>
                {ms(e.p95_ms)}
                {change(before.get(e.endpoint))}
              </td>
              <td>{ms(e.max_ms)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Section>
  );
}

function ScreensSection({
  projectId,
  summary,
  busy,
  onAccept,
}: {
  projectId: string;
  summary: ReportSummary;
  busy: boolean;
  onAccept: () => void;
}) {
  const report = useReport<ScreensReport>(projectId, summary.id);
  const s = summary.summary;
  return (
    <Section
      title="Screenshots"
      right={<Verdict ok={summary.ok} label={s ? `${s.changed ?? 0} of ${s.pages ?? 0} changed` : "screens"} />}
    >
      <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
        <span>
          {time(summary.started_at)} · compared with {s?.baseline ?? "–"}
        </span>
        {!summary.ok && (
          <Button size="sm" variant="outline" disabled={busy} onClick={onAccept}>
            Accept as new baseline
          </Button>
        )}
      </div>
      <div className="grid grid-cols-2 gap-2">
        {report?.pages.map((p) => (
          <figure key={p.path} className="flex flex-col gap-1 text-xs">
            {p.error ? (
              <p className="rounded bg-destructive/5 p-2 text-destructive">{p.error}</p>
            ) : (
              <a href={screenshotUrl(projectId, summary.id, p.file)} target="_blank" rel="noreferrer">
                {/* eslint-disable-next-line @next/next/no-img-element -- served by the API, not a static asset */}
                <img
                  src={screenshotUrl(projectId, summary.id, p.file)}
                  alt={`Screenshot of ${p.path}`}
                  className="rounded border"
                  loading="lazy"
                />
              </a>
            )}
            <figcaption className="flex justify-between gap-1">
              <span className="truncate font-mono">{p.path}</span>
              {p.diff_ratio != null && (
                <a
                  href={p.diff_file ? screenshotUrl(projectId, summary.id, p.diff_file) : undefined}
                  target="_blank"
                  rel="noreferrer"
                  className={p.diff_ratio > 0.002 ? "text-destructive underline" : "text-muted-foreground"}
                >
                  {(p.diff_ratio * 100).toFixed(2)}% differs
                </a>
              )}
            </figcaption>
          </figure>
        ))}
      </div>
    </Section>
  );
}

function Count({ label, value, bad = false }: { label: string; value: number; bad?: boolean }) {
  return (
    <div className="rounded bg-muted/50 py-1">
      <div className={`text-base font-medium ${bad ? "text-destructive" : ""}`}>{value}</div>
      <div className="text-muted-foreground">{label}</div>
    </div>
  );
}

const show = (v: unknown) => (typeof v === "string" ? v : JSON.stringify(v));

function Differences({ items }: { items: Difference[] }) {
  return (
    <table className="w-full table-fixed text-left">
      <thead className="text-muted-foreground">
        <tr>
          <th className="w-1/4 font-normal">Where</th>
          <th className="w-1/4 font-normal">Recorded</th>
          <th className="w-1/4 font-normal">Now</th>
          <th className="w-1/4 font-normal">Verdict</th>
        </tr>
      </thead>
      <tbody>
        {items.map((d, i) => (
          <tr key={i} className="align-top">
            <td className="truncate font-mono" title={d.path || d.where}>
              {d.path || d.where}
            </td>
            <td className="truncate font-mono" title={show(d.before)}>
              {show(d.before)}
            </td>
            <td className="truncate font-mono" title={show(d.after)}>
              {show(d.after)}
            </td>
            <td className={d.verdict === "regression" ? "text-destructive" : "text-muted-foreground"}>
              {d.verdict}
              {d.rule ? ` (${d.rule})` : ""}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function NoiseRules({ projectId, rules, onSaved }: { projectId: string; rules: NoiseRule[]; onSaved: () => void }) {
  const [error, setError] = useState<string | null>(null);
  const toggle = async (rule: NoiseRule, enabled: boolean) => {
    try {
      const builtin = Object.fromEntries(rules.filter((r) => r.builtin).map((r) => [r.id, r.enabled]));
      await setNoiseRules(
        projectId,
        { ...builtin, ...(rule.builtin ? { [rule.id]: enabled } : {}) },
        rules.filter((r) => !r.builtin).map((r) => (r.id === rule.id ? { ...r, enabled } : r)),
      );
      setError(null);
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };
  return (
    <Section title="Noise rules">
      <p className="text-xs text-muted-foreground">
        Differences these rules explain don&apos;t count as regressions. Switch one off to see them as changes.
      </p>
      <ul className="flex flex-col gap-2 text-xs">
        {rules.map((r) => (
          <li key={r.id} className="flex items-start gap-2">
            <Checkbox
              className="mt-0.5"
              checked={r.enabled}
              aria-label={`Noise rule ${r.id}`}
              onCheckedChange={(v) => void toggle(r, Boolean(v))}
            />
            <span>
              <span className="font-mono">{r.id}</span>
              {r.where !== "**" && <span className="text-muted-foreground"> at {r.where}</span>}
              <span className="block text-muted-foreground">{r.description}</span>
            </span>
          </li>
        ))}
      </ul>
      {error && <p className="text-sm text-destructive">{error}</p>}
    </Section>
  );
}
