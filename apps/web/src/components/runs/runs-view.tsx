"use client";

import { Loader2, Play } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  createRun,
  listPlaybooks,
  listRuns,
  PROFILE_LABEL,
  type Playbook,
  type ProfileName,
  type Run,
} from "@/lib/api";

const SELECT_CLASS = "h-8 rounded-lg border border-input bg-transparent px-2.5 text-sm dark:bg-input/30";

interface SchemaProp {
  type?: string;
  enum?: string[];
  default?: unknown;
  description?: string;
  title?: string;
  items?: { type?: string };
}

/** Which of a run's inputs to show; resolves `$ref`-style enums Pydantic emits for Literal fields. */
function inputProps(pb: Playbook): Array<[string, SchemaProp]> {
  const schema = pb.inputs_schema as {
    properties?: Record<string, SchemaProp & { $ref?: string }>;
    $defs?: Record<string, SchemaProp>;
  };
  return Object.entries(schema.properties ?? {}).map(([key, prop]) => {
    const ref = prop.$ref?.split("/").at(-1);
    return [key, ref && schema.$defs?.[ref] ? { ...schema.$defs[ref], ...prop } : prop];
  });
}

function defaults(pb: Playbook): Record<string, unknown> {
  return Object.fromEntries(inputProps(pb).map(([k, p]) => [k, p.default]));
}

export function runTitle(run: Pick<Run, "playbook" | "inputs">): string {
  const request = run.inputs.request;
  if (typeof request === "string") return request.length > 60 ? `${request.slice(0, 57)}…` : request;
  if (run.playbook === "microservices")
    return run.inputs.mode === "conversion" ? "Full conversion" : "Architecture audit";
  return run.playbook;
}

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
                        {runTitle(r)}
                        <span className="ml-2 font-mono text-xs text-muted-foreground">{r.id.slice(0, 8)}</span>
                      </span>
                      <span className="text-xs text-muted-foreground">
                        {r.playbook} · tier {r.tier} · {new Date(r.created_at).toLocaleString()} ·{" "}
                        {PROFILE_LABEL[r.llm_profile]}
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
  const [playbooks, setPlaybooks] = useState<Playbook[] | null>(null);
  const [name, setName] = useState("sample");
  const [inputs, setInputs] = useState<Record<string, unknown>>({});
  const [tier, setTier] = useState<number | null>(null);
  const [profile, setProfile] = useState<ProfileName | "">("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listPlaybooks()
      .then((list) => {
        setPlaybooks(list);
        const first = list.find((p) => p.name === "sample") ?? list[0];
        if (first) {
          setName(first.name);
          setInputs(defaults(first));
        }
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  const pb = useMemo(() => playbooks?.find((p) => p.name === name), [playbooks, name]);
  const set = (key: string, value: unknown) => setInputs((prev) => ({ ...prev, [key]: value }));

  return (
    <Card>
      <CardHeader>
        <CardTitle>Start a run</CardTitle>
        <CardDescription>
          Pick a playbook. The sample playbook plans and writes a short brief with a real agent team; turn off “use llm”
          to try the flow without a model server. Tier sets how many approvals you get (it can only go up).
        </CardDescription>
      </CardHeader>
      <CardContent>
        {!playbooks && !error && <p className="text-sm text-muted-foreground">Loading playbooks…</p>}
        {pb && (
          <form
            className="grid gap-4 sm:grid-cols-3"
            onSubmit={async (e) => {
              e.preventDefault();
              setBusy(true);
              setError(null);
              try {
                const run = await createRun({
                  playbook: pb.name,
                  inputs,
                  llm_profile: profile || undefined,
                  tier: tier ?? undefined,
                });
                router.push(`/runs/${run.id}`);
              } catch (err) {
                setError(err instanceof Error ? err.message : String(err));
                setBusy(false);
              }
            }}
          >
            <div className="grid gap-1.5">
              <Label htmlFor="run-playbook">Playbook</Label>
              <select
                id="run-playbook"
                className={SELECT_CLASS}
                value={pb.name}
                onChange={(e) => {
                  const next = playbooks?.find((p) => p.name === e.target.value);
                  if (!next) return;
                  setName(next.name);
                  setInputs(defaults(next));
                  setTier(null);
                }}
              >
                {playbooks?.map((p) => (
                  <option key={p.name} value={p.name}>
                    {p.title}
                  </option>
                ))}
              </select>
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="run-tier">Tier</Label>
              <select
                id="run-tier"
                className={SELECT_CLASS}
                value={tier ?? pb.tier}
                onChange={(e) => setTier(Number(e.target.value))}
              >
                {[0, 1, 2, 3]
                  .filter((t) => t >= pb.tier)
                  .map((t) => (
                    <option key={t} value={t}>
                      Tier {t}
                      {t === pb.tier ? " (default)" : ""}
                    </option>
                  ))}
              </select>
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="run-profile">Model</Label>
              <select
                id="run-profile"
                className={SELECT_CLASS}
                value={profile}
                onChange={(e) => setProfile(e.target.value as ProfileName | "")}
              >
                <option value="">Active profile (Settings)</option>
                <option value="remote_gpu">Remote GPU</option>
                <option value="local_cpu">Local CPU</option>
              </select>
            </div>
            <p className="text-sm text-muted-foreground sm:col-span-3">{pb.description}</p>
            {inputProps(pb).map(([key, prop]) => (
              <InputField key={key} id={key} prop={prop} value={inputs[key]} onChange={(v) => set(key, v)} />
            ))}
            <div className="sm:col-span-3">
              <Button type="submit" disabled={busy}>
                {busy ? <Loader2 className="animate-spin" aria-hidden="true" /> : <Play aria-hidden="true" />}
                Start run
              </Button>
            </div>
          </form>
        )}
        {error && (
          <p role="alert" className="mt-2 text-sm text-destructive">
            {error}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function InputField({
  id,
  prop,
  value,
  onChange,
}: {
  id: string;
  prop: SchemaProp;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const label = prop.title ?? id;
  const fieldId = `run-input-${id}`;
  if (prop.type === "boolean") {
    return (
      <label className="flex items-center gap-2 text-sm sm:col-span-3" title={prop.description}>
        <input type="checkbox" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />
        {label}
        {prop.description && <span className="text-xs text-muted-foreground">{prop.description}</span>}
      </label>
    );
  }
  if (prop.enum) {
    return (
      <div className="grid gap-1.5">
        <Label htmlFor={fieldId}>{label}</Label>
        <select
          id={fieldId}
          className={SELECT_CLASS}
          value={String(value ?? "")}
          onChange={(e) => onChange(e.target.value)}
        >
          {prop.enum.map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </select>
      </div>
    );
  }
  if (prop.type === "number" || prop.type === "integer") {
    return (
      <div className="grid gap-1.5">
        <Label htmlFor={fieldId}>{label}</Label>
        <Input
          id={fieldId}
          type="number"
          value={String(value ?? "")}
          onChange={(e) => onChange(Number(e.target.value))}
        />
      </div>
    );
  }
  if (prop.type === "array") {
    return (
      <div className="grid gap-1.5 sm:col-span-2">
        <Label htmlFor={fieldId}>{label} (comma-separated)</Label>
        <Input
          id={fieldId}
          value={Array.isArray(value) ? value.join(", ") : ""}
          onChange={(e) =>
            onChange(
              e.target.value
                .split(",")
                .map((v) => v.trim())
                .filter(Boolean),
            )
          }
        />
      </div>
    );
  }
  return (
    <div className="grid gap-1.5 sm:col-span-3">
      <Label htmlFor={fieldId}>{label}</Label>
      <Textarea id={fieldId} rows={3} value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}
