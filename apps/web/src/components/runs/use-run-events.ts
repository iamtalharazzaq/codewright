"use client";

import { useEffect, useState } from "react";

import type { RunEvent, TokenEvent } from "@/lib/api";

const MAX_LIVE_CHARS = 8000;

/** Subscribes to the run's Server-Sent Events. The browser reconnects by itself and resumes via Last-Event-ID.
 *
 * `live` is the model's output as it streams (tokens are not stored, so it starts empty after a reload). */
export function useRunEvents(runId: string): {
  events: RunEvent[];
  connected: boolean;
  live: { agent: string; text: string } | null;
} {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [live, setLive] = useState<{ agent: string; text: string } | null>(null);

  useEffect(() => {
    const source = new EventSource(`/api/runs/${runId}/events`);
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);
    source.addEventListener("run_event", (msg) => {
      const event = JSON.parse((msg as MessageEvent<string>).data) as RunEvent;
      setEvents((prev) => (prev.some((e) => e.id === event.id) ? prev : [...prev, event]));
      if (event.type === "step_started") setLive(null);
    });
    source.addEventListener("token", (msg) => {
      const token = JSON.parse((msg as MessageEvent<string>).data) as TokenEvent;
      setLive((prev) =>
        prev && prev.agent === token.agent
          ? { agent: token.agent, text: (prev.text + token.text).slice(-MAX_LIVE_CHARS) }
          : { agent: token.agent, text: token.text },
      );
    });
    return () => source.close();
  }, [runId]);

  return { events, connected, live };
}
