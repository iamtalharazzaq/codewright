"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  getVerification,
  startVerification,
  verificationEventsUrl,
  type VerificationActivity,
  type VerificationStatus,
  type VerifyAction,
} from "@/lib/api";

const MAX_LINES = 400;

export interface LiveLine {
  key: number;
  text: string;
  tone: "note" | "ok" | "bad" | "muted";
}

export interface LiveActivity {
  activity: VerificationActivity;
  lines: LiveLine[];
  status: VerificationActivity["status"];
  error: string | null;
  recorderUrl: string | null; // the live recorder's address while it runs
}

/**
 * A project's verification (CODEWRIGHT.md Phase 7): saved recordings and reports, plus the running action's live
 * events from `/api/projects/<id>/verification/actions/<aid>/events`, replayed on reconnect.
 */
export function useVerification(projectId: string) {
  const [status, setStatus] = useState<VerificationStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [live, setLive] = useState<LiveActivity | null>(null);
  const following = useRef<string | null>(null);
  const source = useRef<EventSource | null>(null);

  const reload = useCallback(async () => {
    try {
      const s = await getVerification(projectId);
      setStatus(s);
      setError(null);
      return s;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return null;
    }
  }, [projectId]);

  const follow = useCallback(
    (activity: VerificationActivity) => {
      if (following.current === activity.id) return;
      source.current?.close();
      following.current = activity.id;
      let key = 0;
      setLive({ activity, lines: [], status: activity.status, error: activity.error, recorderUrl: null });
      const es = new EventSource(verificationEventsUrl(projectId, activity.id));
      source.current = es;
      const add = (text: string, tone: LiveLine["tone"] = "note") =>
        setLive((l) => (l ? { ...l, lines: [...l.lines, { key: ++key, text, tone }].slice(-MAX_LINES) } : l));
      const on = (type: string, fn: (d: Record<string, unknown>) => void) =>
        es.addEventListener(type, (e) => fn(JSON.parse((e as MessageEvent<string>).data) as Record<string, unknown>));
      on("note", (d) => add(String(d.text)));
      on("recorder", (d) => {
        setLive((l) => (l ? { ...l, recorderUrl: (d.url as string) ?? null } : l));
        add(String(d.text), "ok");
      });
      on("error", (d) => {
        if (d.message) add(String(d.message), "bad");
      });
      on("exchange", (d) => {
        const x = d.exchange as { method: string; path: string; status: number | null; journey: string };
        add(
          `${x.journey}: ${x.method} ${x.path} → ${x.status ?? "no answer"}`,
          (x.status ?? 500) >= 500 ? "bad" : "muted",
        );
      });
      on("replayed", (d) => {
        const r = d.result as { method: string; path: string; status_after: number | null; regressions: number };
        add(
          `${r.method} ${r.path} → ${r.status_after ?? "no answer"}${r.regressions ? ` · ${r.regressions} regression(s)` : ""}`,
          r.regressions ? "bad" : "muted",
        );
      });
      on("result", (d) => {
        const r = d.result as { component: string; ok: boolean };
        add(`${r.component}: ${r.ok ? "passed" : "failed"}`, r.ok ? "ok" : "bad");
      });
      on("done", (d) => {
        es.close();
        source.current = null;
        setLive((l) =>
          l
            ? {
                ...l,
                status: d.status as LiveActivity["status"],
                error: (d.error as string) ?? null,
                recorderUrl: null,
              }
            : l,
        );
        void reload();
      });
      es.onerror = () => {
        // The server closes the stream when the action ends; reconnecting would only replay it.
        if (es.readyState === EventSource.CLOSED) source.current = null;
      };
    },
    [projectId, reload],
  );

  useEffect(() => {
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- loading data on mount
    void reload().then((s) => {
      const running = s?.activities.find((a) => a.status === "running");
      if (!cancelled && running) follow(running);
    });
    return () => {
      cancelled = true;
      source.current?.close();
      source.current = null;
      following.current = null;
    };
  }, [reload, follow]);

  const start = useCallback(
    async (action: VerifyAction, options: Record<string, unknown> = {}) => {
      try {
        const activity = await startVerification(projectId, action, options);
        setError(null);
        follow(activity);
        void reload();
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [projectId, follow, reload],
  );

  const busy = live?.status === "running" || Boolean(status?.running);
  return { status, error, live, busy, start, reload };
}
