"use client";

import { useEffect, useState } from "react";

import type { RunEvent } from "@/lib/api";

/** Subscribes to the run's Server-Sent Events. The browser reconnects by itself and resumes via Last-Event-ID. */
export function useRunEvents(runId: string): { events: RunEvent[]; connected: boolean } {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    const source = new EventSource(`/api/runs/${runId}/events`);
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);
    source.addEventListener("run_event", (msg) => {
      const event = JSON.parse((msg as MessageEvent<string>).data) as RunEvent;
      setEvents((prev) => (prev.some((e) => e.id === event.id) ? prev : [...prev, event]));
    });
    return () => source.close();
  }, [runId]);

  return { events, connected };
}
