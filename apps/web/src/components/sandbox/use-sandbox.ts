"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  activityEventsUrl,
  getSandbox,
  startSandboxAction,
  stopPreview,
  stopSandbox,
  type ActionResult,
  type Preview,
  type SandboxAction,
  type SandboxActivity,
  type SandboxStatus,
  type TestReport,
} from "@/lib/api";

const MAX_OUTPUT = 200_000; // characters kept per step in the browser

export interface LogStep {
  key: number;
  component: string;
  name: string;
  cmd: string[];
  network: string;
  status: "running" | "ok" | "failed";
  duration?: number;
  output: string;
}

export interface ActivityLog {
  activity: SandboxActivity;
  steps: LogStep[];
  notes: string[];
  reports: { component: string; report: TestReport }[];
  results: ActionResult[];
  status: SandboxActivity["status"];
  error: string | null;
}

/**
 * A project's sandbox (CODEWRIGHT.md Phase 5): its components, the latest build/test/lint/run with live output, and
 * the running previews. Output streams from `/api/projects/<id>/sandbox/actions/<aid>/events` and is replayed on
 * reconnect, so a reload in the middle of a build shows everything so far.
 */
export function useSandbox(projectId: string) {
  const [status, setStatus] = useState<SandboxStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [log, setLog] = useState<ActivityLog | null>(null);
  const following = useRef<string | null>(null);
  const source = useRef<EventSource | null>(null);

  const reload = useCallback(async () => {
    try {
      const s = await getSandbox(projectId);
      setStatus(s);
      setError(null);
      return s;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return null;
    }
  }, [projectId]);

  const follow = useCallback(
    (activity: SandboxActivity) => {
      if (following.current === activity.id) return;
      source.current?.close();
      following.current = activity.id;
      let component = activity.components[0] ?? ".";
      let key = 0;
      setLog({
        activity,
        steps: [],
        notes: [],
        reports: [],
        results: [],
        status: activity.status,
        error: activity.error,
      });
      const es = new EventSource(activityEventsUrl(projectId, activity.id));
      source.current = es;
      const on = (type: string, fn: (data: Record<string, unknown>) => void) =>
        es.addEventListener(type, (e) => fn(JSON.parse((e as MessageEvent<string>).data) as Record<string, unknown>));
      const update = (fn: (l: ActivityLog) => ActivityLog) => setLog((l) => (l ? fn(l) : l));
      on("component", (d) => {
        component = String(d.path);
      });
      on("step", (d) =>
        update((l) => ({
          ...l,
          steps: [
            ...l.steps,
            {
              key: ++key,
              component,
              name: String(d.name),
              cmd: d.cmd as string[],
              network: String(d.network),
              status: "running",
              output: "",
            },
          ],
        })),
      );
      on("output", (d) =>
        update((l) => {
          const steps = l.steps.slice();
          const last = steps.at(-1);
          if (last) steps[steps.length - 1] = { ...last, output: (last.output + String(d.text)).slice(-MAX_OUTPUT) };
          return { ...l, steps };
        }),
      );
      on("step_done", (d) =>
        update((l) => {
          const r = d.result as { ok: boolean; duration_s: number };
          const steps = l.steps.slice();
          const last = steps.at(-1);
          if (last) steps[steps.length - 1] = { ...last, status: r.ok ? "ok" : "failed", duration: r.duration_s };
          return { ...l, steps };
        }),
      );
      on("note", (d) => update((l) => ({ ...l, notes: [...l.notes, String(d.text)] })));
      on("report", (d) =>
        update((l) => ({ ...l, reports: [...l.reports, { component, report: d.report as TestReport }] })),
      );
      on("result", (d) => update((l) => ({ ...l, results: [...l.results, d.result as ActionResult] })));
      on("preview", () => void reload());
      on("error", (d) => {
        if (d && typeof d === "object" && "message" in d) update((l) => ({ ...l, error: String(d.message) }));
      });
      on("done", (d) => {
        update((l) => ({ ...l, status: d.status as SandboxActivity["status"], error: (d.error as string) ?? l.error }));
        es.close();
        void reload();
      });
    },
    [projectId, reload],
  );

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- loading data on mount
    void reload().then((s) => {
      const latest = s?.activities[0];
      if (latest) follow(latest);
    });
    const timer = setInterval(() => void reload(), 10_000); // previews can exit on their own
    return () => {
      clearInterval(timer);
      source.current?.close();
      following.current = null;
    };
  }, [reload, follow]);

  const start = useCallback(
    async (action: SandboxAction, components: string[] = []) => {
      try {
        const activity = await startSandboxAction(projectId, action, components);
        follow(activity);
        await reload();
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [projectId, follow, reload],
  );

  const stopOne = useCallback(
    async (preview: Preview) => {
      await stopPreview(projectId, preview.id).catch(() => undefined);
      await reload();
    },
    [projectId, reload],
  );

  const stopAll = useCallback(async () => {
    await stopSandbox(projectId).catch(() => undefined);
    await reload();
  }, [projectId, reload]);

  const busy = log?.status === "running";
  const previews = status?.session?.previews ?? [];
  return { status, error, log, busy, previews, start, stopOne, stopAll, reload };
}
