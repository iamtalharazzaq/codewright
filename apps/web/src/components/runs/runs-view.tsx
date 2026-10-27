"use client";

import { Loader2, Play } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { createRun, listRuns, PROFILE_LABEL, type ProfileName, type ProjectMode, type Run } from "@/lib/api";

export function RunsView() {
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listRuns()
      .then(setRuns)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  return (
    <div className="flex flex-col gap-6">
      <StartRunCard />
      <Card>
        <CardHeader>
          <CardTitle>Recent runs</CardTitle>
        </CardHeader>
        <CardContent>
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          {!runs && !error && <p className="text-sm text-muted-foreground">Loading…</p>}
          {runs?.length === 0 && <p className="text-sm text-muted-foreground">No runs yet.</p>}
          {runs && runs.length > 0 && (
            <ul className="divide-y">
              {runs.map((r) => (
                <li key={r.id}>
                  <Link
                    href={`/runs/${r.id}`}
                    className="flex flex-wrap items-center justify-between gap-2 rounded-md px-2 py-3 hover:bg-muted"
                  >
                    <span className="flex flex-col">
                      <span className="font-medium">
                        {r.mode === "audit" ? "Architecture audit" : "Full conversion"}
                        <span className="ml-2 font-mono text-xs text-muted-foreground">{r.id.slice(0, 8)}</span>
                      </span>
                      <span className="text-xs text-muted-foreground">
                        {new Date(r.created_at).toLocaleString()} · {PROFILE_LABEL[r.llm_profile]}
                        {r.current_step ? ` · ${r.current_step}` : ""}
                      </span>
                    </span>
                    <StatusBadge status={r.status} />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function StartRunCard() {
  const router = useRouter();
  const [mode, setMode] = useState<ProjectMode>("audit");
  const [profile, setProfile] = useState<ProfileName | "">("");
  const [delay, setDelay] = useState("2");
  const [useLLM, setUseLLM] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Start a stub run</CardTitle>
        <CardDescription>
          Phase 1 runs the whole workflow with placeholder steps, so you can try the gates, pause/resume and the model
          switch. Real projects arrive with the importers in Phase 2.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form
          className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4 lg:items-end"
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            setError(null);
            try {
              const run = await createRun({
                project_name: "Demo project",
                mode,
                llm_profile: profile || undefined,
                options: { stub_delay_s: Number(delay), use_llm: useLLM },
              });
              router.push(`/runs/${run.id}`);
            } catch (err) {
              setError(err instanceof Error ? err.message : String(err));
              setBusy(false);
            }
          }}
        >
          <div className="grid gap-1.5">
            <Label htmlFor="run-mode">Mode</Label>
            <select
              id="run-mode"
              className="h-8 rounded-lg border border-input bg-transparent px-2.5 text-sm dark:bg-input/30"
              value={mode}
              onChange={(e) => setMode(e.target.value as ProjectMode)}
            >
              <option value="audit">Architecture audit (B)</option>
              <option value="conversion">Full conversion (A)</option>
            </select>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="run-profile">Model</Label>
            <select
              id="run-profile"
              className="h-8 rounded-lg border border-input bg-transparent px-2.5 text-sm dark:bg-input/30"
              value={profile}
              onChange={(e) => setProfile(e.target.value as ProfileName | "")}
            >
              <option value="">Active profile (Settings)</option>
              <option value="remote_gpu">Remote GPU</option>
              <option value="local_cpu">Local CPU</option>
            </select>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="run-delay">Seconds per step</Label>
            <Input
              id="run-delay"
              type="number"
              min={0}
              max={60}
              value={delay}
              onChange={(e) => setDelay(e.target.value)}
            />
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={useLLM} onChange={(e) => setUseLLM(e.target.checked)} />
            One real LLM call at intake
          </label>
          <div className="sm:col-span-2 lg:col-span-4">
            <Button type="submit" disabled={busy}>
              {busy ? <Loader2 className="animate-spin" aria-hidden="true" /> : <Play aria-hidden="true" />}
              Start run
            </Button>
            {error && (
              <p role="alert" className="mt-2 text-sm text-destructive">
                {error}
              </p>
            )}
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
