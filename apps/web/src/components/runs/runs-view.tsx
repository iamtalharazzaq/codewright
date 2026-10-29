"use client";

import { Loader2, Play } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type ReactNode, useEffect, useMemo, useState } from "react";

import { FormSelect, type SelectOption } from "@/components/form-select";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
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

const TIERS: SelectOption[] = [
  { value: "0", label: "Tier 0", hint: "Answer only, no approvals" },
  { value: "1", label: "Tier 1", hint: "Approve the result" },
  { value: "2", label: "Tier 2", hint: "Approve the plan and the result" },
  { value: "3", label: "Tier 3", hint: "Every gate the playbook defines" },
];

const MODELS: SelectOption[] = [
  { value: "", label: "Active profile", hint: "The model chosen in Settings" },
  { value: "remote_gpu", label: "Remote GPU" },
  { value: "local_cpu", label: "Local CPU" },
];

interface SchemaProp {
  type?: string;
  enum?: string[];
  default?: unknown;
  description?: string;
  title?: string;
  items?: { type?: string };
  "x-advanced"?: boolean;
  "x-available"?: string[];
}

/** A run's inputs; resolves `$ref`-style enums Pydantic emits for Literal fields. */
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

const humanize = (v: string) => (v.charAt(0).toUpperCase() + v.slice(1)).replaceAll("_", " ");

function defaults(pb: Playbook): Record<string, unknown> {
  return Object.fromEntries(inputProps(pb).map(([k, p]) => [k, p.default]));
}

export function runTitle(run: Pick<Run, "playbook" | "inputs">): string {
  const request = run.inputs.request;
  if (typeof request === "string" && request) return request.length > 60 ? `${request.slice(0, 57)}…` : request;
  if (run.playbook === "architecture_change") {
    const target = humanize(String(run.inputs.target ?? "microservices"));
    return `${target}: ${run.inputs.mode === "conversion" ? "conversion" : "audit"}`;
  }
  return humanize(run.playbook);
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
                        {humanize(r.playbook)} · tier {r.tier} · {new Date(r.created_at).toLocaleString()} ·{" "}
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
  // Test knobs (x-advanced) keep their defaults and aren't shown.
  const fields = pb ? inputProps(pb).filter(([, p]) => !p["x-advanced"]) : [];

  return (
    <Card>
      <CardHeader>
        <CardTitle>Start a run</CardTitle>
        <CardDescription>
          Pick a playbook and fill in its inputs. The tier sets how many approvals you give.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {!playbooks && !error && <p className="text-sm text-muted-foreground">Loading playbooks…</p>}
        {pb && (
          <form
            className="flex flex-col gap-5"
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
            <div className="grid gap-4 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)]">
              <Field id="run-playbook" label="Playbook">
                <FormSelect
                  id="run-playbook"
                  value={pb.name}
                  options={(playbooks ?? []).map((p) => ({ value: p.name, label: p.title }))}
                  onChange={(v) => {
                    const next = playbooks?.find((p) => p.name === v);
                    if (!next) return;
                    setName(next.name);
                    setInputs(defaults(next));
                    setTier(null);
                  }}
                />
              </Field>
              <Field id="run-tier" label="Tier">
                <FormSelect
                  id="run-tier"
                  value={String(tier ?? pb.tier)}
                  options={TIERS.filter((t) => Number(t.value) >= pb.tier).map((t) =>
                    Number(t.value) === pb.tier ? { ...t, label: `${t.label} (default)` } : t,
                  )}
                  onChange={(v) => setTier(Number(v))}
                />
              </Field>
              <Field id="run-profile" label="Model">
                <FormSelect
                  id="run-profile"
                  value={profile}
                  options={MODELS}
                  onChange={(v) => setProfile(v as ProfileName | "")}
                />
              </Field>
            </div>
            <p className="rounded-lg bg-muted/50 px-3 py-2 text-sm text-muted-foreground">{pb.description}</p>
            {fields.length > 0 && (
              <div className="grid gap-4 sm:grid-cols-2">
                {fields.map(([key, prop]) => (
                  <InputField key={key} id={key} prop={prop} value={inputs[key]} onChange={(v) => set(key, v)} />
                ))}
              </div>
            )}
            <div>
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

function Field({
  id,
  label,
  hint,
  className,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={`flex flex-col gap-1.5 ${className ?? ""}`}>
      <Label htmlFor={id}>{label}</Label>
      {children}
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
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
  const label = prop.title ?? humanize(id);
  const fieldId = `run-input-${id}`;
  if (prop.type === "boolean") {
    return (
      <label className="flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors hover:bg-muted/50 has-data-checked:border-primary/40 sm:col-span-2">
        <Checkbox id={fieldId} className="mt-0.5" checked={Boolean(value)} onCheckedChange={(c) => onChange(c)} />
        <span className="flex flex-col gap-0.5">
          <span className="text-sm font-medium">{label}</span>
          {prop.description && <span className="text-xs text-muted-foreground">{prop.description}</span>}
        </span>
      </label>
    );
  }
  if (prop.enum) {
    const available = prop["x-available"];
    return (
      <Field id={fieldId} label={label} hint={prop.description}>
        <FormSelect
          id={fieldId}
          value={String(value ?? "")}
          options={prop.enum.map((v) => ({
            value: v,
            label: humanize(v),
            disabled: available ? !available.includes(v) : false,
          }))}
          onChange={onChange}
        />
      </Field>
    );
  }
  if (prop.type === "number" || prop.type === "integer") {
    return (
      <Field id={fieldId} label={label} hint={prop.description}>
        <Input
          id={fieldId}
          type="number"
          className="h-9"
          value={String(value ?? "")}
          onChange={(e) => onChange(Number(e.target.value))}
        />
      </Field>
    );
  }
  if (prop.type === "array") {
    return (
      <Field id={fieldId} label={label} hint={prop.description ?? "Separate with commas."} className="sm:col-span-2">
        <Input
          id={fieldId}
          className="h-9"
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
      </Field>
    );
  }
  return (
    <Field id={fieldId} label={label} hint={prop.description} className="sm:col-span-2">
      <Textarea id={fieldId} rows={3} value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} />
    </Field>
  );
}
