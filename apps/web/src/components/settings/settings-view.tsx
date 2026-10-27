"use client";

import { Cpu, Loader2, RefreshCw, Server } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  checkHealth,
  getSettings,
  PROFILE_LABEL,
  updateLLMSettings,
  type HealthView,
  type ProfileName,
  type SettingsView as Settings,
} from "@/lib/api";

const PROFILES: ProfileName[] = ["remote_gpu", "local_cpu"];
const HINT: Record<ProfileName, string> = {
  remote_gpu: "llama.cpp on your RTX 3080 box, through a secure tunnel (Tailscale or SSH). Fast.",
  local_cpu: "llama.cpp on this machine. Slow, but always available.",
};

export function SettingsView() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [health, setHealth] = useState<Partial<Record<ProfileName, HealthView>>>({});
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refreshHealth = useCallback(async () => {
    setChecking(true);
    try {
      const reports = await checkHealth();
      setHealth(Object.fromEntries(reports.map((r) => [r.profile, r])));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setChecking(false);
    }
  }, []);

  useEffect(() => {
    const fail = (e: unknown) => setError(e instanceof Error ? e.message : String(e));
    getSettings().then(setSettings).catch(fail);
    checkHealth()
      .then((reports) => setHealth(Object.fromEntries(reports.map((r) => [r.profile, r]))))
      .catch(fail);
  }, []);

  async function save(change: Parameters<typeof updateLLMSettings>[0]) {
    setError(null);
    try {
      setSettings(await updateLLMSettings(change));
      await refreshHealth();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  if (!settings) {
    return error ? (
      <p role="alert" className="text-sm text-destructive">
        {error}
      </p>
    ) : (
      <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" aria-hidden="true" /> Loading settings…
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {error && (
        <p
          role="alert"
          className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive"
        >
          {error}
        </p>
      )}
      <Card>
        <CardHeader>
          <CardTitle>Language model</CardTitle>
          <CardDescription>
            Both options run Qwen3.5 9B on llama.cpp and are used through the same API, so switching only changes the
            URL. New runs use the active profile; you can also pick one per run.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <fieldset className="grid gap-3 sm:grid-cols-2">
            <legend className="sr-only">Active profile</legend>
            {PROFILES.map((name) => {
              const active = settings.active_llm_profile === name;
              const Icon = name === "remote_gpu" ? Server : Cpu;
              return (
                <label
                  key={name}
                  className="flex cursor-pointer items-start gap-3 rounded-lg border p-3 has-checked:border-brand has-checked:bg-brand/5 has-focus-visible:ring-3 has-focus-visible:ring-ring/50"
                >
                  <input
                    type="radio"
                    name="active-profile"
                    className="mt-1 accent-(--brand)"
                    checked={active}
                    onChange={() => void save({ active_profile: name })}
                  />
                  <span className="flex flex-col gap-1">
                    <span className="flex items-center gap-2 font-medium">
                      <Icon className="size-4" aria-hidden="true" />
                      {PROFILE_LABEL[name]}
                      {health[name] && <StatusBadge status={health[name].status} />}
                    </span>
                    <span className="text-xs text-muted-foreground">{HINT[name]}</span>
                  </span>
                </label>
              );
            })}
          </fieldset>
          <div>
            <Button variant="outline" size="sm" onClick={() => void refreshHealth()} disabled={checking}>
              <RefreshCw className={checking ? "animate-spin" : undefined} aria-hidden="true" />
              Check connection
            </Button>
          </div>
        </CardContent>
      </Card>

      {PROFILES.map((name) => (
        <ProfileCard
          key={name}
          name={name}
          profile={settings.llm_profiles[name]}
          health={health[name]}
          onSave={(change) => save({ profiles: { [name]: change } })}
        />
      ))}

      <Card>
        <CardHeader>
          <CardTitle>Privacy</CardTitle>
          <CardDescription>
            External LLM providers are {settings.external_llm_enabled ? "ENABLED: code may leave this machine" : "off"}.
            Embeddings: {settings.embeddings_model}.
          </CardDescription>
        </CardHeader>
      </Card>
    </div>
  );
}

function ProfileCard({
  name,
  profile,
  health,
  onSave,
}: {
  name: ProfileName;
  profile: Settings["llm_profiles"][ProfileName];
  health: HealthView | undefined;
  onSave: (change: { base_url: string; model: string; num_ctx: number }) => Promise<void>;
}) {
  const [url, setUrl] = useState(profile.base_url ?? "");
  const [model, setModel] = useState(profile.model);
  const [ctx, setCtx] = useState(String(profile.num_ctx));
  const [saving, setSaving] = useState(false);
  const id = `profile-${name}`;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          {PROFILE_LABEL[name]}
          {health && <StatusBadge status={health.status} />}
        </CardTitle>
        <CardDescription>
          {health?.status === "ok"
            ? `Reachable in ${health.latency_ms} ms · ${health.server_slots ?? "?"} slots × ${health.server_ctx ?? "?"} tokens`
            : (health?.detail ?? "Not checked yet.")}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form
          className="grid gap-4 sm:grid-cols-[2fr_1fr_8rem_auto] sm:items-end"
          onSubmit={async (e) => {
            e.preventDefault();
            setSaving(true);
            await onSave({ base_url: url.trim(), model: model.trim(), num_ctx: Number(ctx) });
            setSaving(false);
          }}
        >
          <div className="grid gap-1.5">
            <Label htmlFor={`${id}-url`}>Server URL</Label>
            <Input
              id={`${id}-url`}
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder={name === "remote_gpu" ? "http://100.64.0.5:8080/v1" : "http://host.docker.internal:8080/v1"}
              inputMode="url"
              spellCheck={false}
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor={`${id}-model`}>Model</Label>
            <Input id={`${id}-model`} value={model} onChange={(e) => setModel(e.target.value)} spellCheck={false} />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor={`${id}-ctx`}>Context (tokens)</Label>
            <Input
              id={`${id}-ctx`}
              type="number"
              min={1024}
              step={1024}
              value={ctx}
              onChange={(e) => setCtx(e.target.value)}
            />
          </div>
          <Button type="submit" disabled={saving}>
            {saving && <Loader2 className="animate-spin" aria-hidden="true" />}
            Save
          </Button>
        </form>
        {health && health.warnings.length > 0 && (
          <ul className="mt-4 flex flex-col gap-1 text-sm text-warning">
            {health.warnings.map((w) => (
              <li key={w}>⚠ {w}</li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
