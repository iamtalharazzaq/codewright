"use client";

import { useCallback, useEffect, useState } from "react";

import { getConversation, type ChatMessage, type ConversationDetail } from "@/lib/api";

/**
 * A conversation's branch on screen, kept live: tokens are appended to the streaming reply, `message` events replace
 * a message (or add one), `run` events bump `runTick` so run cards refresh. On (re)connect the thread is reloaded.
 */
export function useConversation(id: string | null) {
  const [detail, setDetail] = useState<ConversationDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [runTick, setRunTick] = useState(0);

  const reload = useCallback(async () => {
    if (!id) return;
    try {
      setDetail(await getConversation(id));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [id]);

  useEffect(() => {
    if (!id) return; // a new chat: the view is remounted (keyed by id) once it has one
    // Load on (re)connect, so nothing streamed while disconnected is missed; also on error, so the thread still
    // shows when live updates are unavailable.
    const source = new EventSource(`/api/conversations/${id}/events`);
    source.onopen = () => void reload();
    source.onerror = () => void reload();
    source.addEventListener("token", (e) => {
      const { message_id, text } = JSON.parse((e as MessageEvent<string>).data) as {
        message_id: string;
        text: string;
      };
      setDetail(
        (d) =>
          d && {
            ...d,
            messages: d.messages.map((m) => (m.id === message_id ? { ...m, content: m.content + text } : m)),
          },
      );
    });
    source.addEventListener("message", (e) => {
      const { message } = JSON.parse((e as MessageEvent<string>).data) as { message: ChatMessage };
      setDetail((d) => {
        if (!d) return d;
        const known = d.messages.some((m) => m.id === message.id);
        const messages = known
          ? d.messages.map((m) => (m.id === message.id ? { ...message, siblings: m.siblings } : m))
          : [...d.messages, message];
        const busy = messages.some((m) => m.status === "streaming");
        return { ...d, messages, busy };
      });
    });
    source.addEventListener("run", () => setRunTick((t) => t + 1));
    return () => source.close();
  }, [id, reload]);

  return { detail, setDetail, error, reload, runTick };
}
