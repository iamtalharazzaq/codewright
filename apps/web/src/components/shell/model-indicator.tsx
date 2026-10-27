"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { LLM_CHANGED } from "@/components/chat/model-picker";
import { checkHealth, getSettings, PROFILE_LABEL, type HealthView, type ProfileName } from "@/lib/api";
import { cn } from "@/lib/utils";

type State =
  | { kind: "loading" }
  | { kind: "error" }
  | { kind: "ready"; profile: ProfileName; model: string; health: HealthView | null };

const DOT: Record<HealthView["status"], string> = {
  ok: "bg-success",
  loading: "bg-warning",
  not_configured: "bg-muted-foreground",
  unreachable: "bg-destructive",
  error: "bg-destructive",
};

/** Sidebar footer: the active LLM profile and its server health (README 2.2 "Model picker"). */
export function ModelIndicator() {
  const [state, setState] = useState<State>({ kind: "loading" });

  const [version, setVersion] = useState(0);

  useEffect(() => {
    const bump = () => setVersion((v) => v + 1);
    window.addEventListener(LLM_CHANGED, bump);
    return () => window.removeEventListener(LLM_CHANGED, bump);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    (async () => {
      const settings = await getSettings(controller.signal);
      const profile = settings.active_llm_profile;
      const model = settings.llm_profiles[profile].model;
      setState({ kind: "ready", profile, model, health: null });
      const [health] = await checkHealth(controller.signal, profile);
      setState({ kind: "ready", profile, model, health: health ?? null });
    })().catch(() => {
      if (!controller.signal.aborted) setState({ kind: "error" });
    });
    return () => controller.abort();
  }, [version]);

  const status = state.kind === "ready" ? (state.health?.status ?? "loading") : null;
  const label =
    state.kind === "loading"
      ? "Checking model…"
      : state.kind === "error"
        ? "Model status unavailable"
        : `${PROFILE_LABEL[state.profile]} · ${state.model}`;
  const detail = status ? `Model server: ${status.replaceAll("_", " ")}` : label;

  return (
    <Link
      href="/settings"
      title={detail}
      className="flex min-w-0 items-center gap-2 rounded-md px-2 py-1.5 text-xs text-muted-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
    >
      <span
        aria-hidden="true"
        className={cn("size-2 shrink-0 rounded-full", status ? DOT[status] : "bg-muted-foreground/50")}
      />
      <span className="truncate">{label}</span>
      <span className="sr-only">. {detail}. Open settings.</span>
    </Link>
  );
}
