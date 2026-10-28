"use client";

import { AlertTriangle, Loader2, MessageSquarePlus, ShieldAlert, Trash2, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { GraphView } from "@/components/graph/graph-view";
import { DeliverPanel } from "@/components/projects/deliver-panel";
import { StatusBadge } from "@/components/projects/project-status";
import { SandboxPanel } from "@/components/sandbox/sandbox-panel";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  addMemory,
  deleteMemory,
  deleteProject,
  getProject,
  notifyProjectsChanged,
  patchProject,
  type ProjectDetail,
} from "@/lib/api";

/** Project home (CODEWRIGHT.md Section 2.3): what's in it, instructions, memory, chats, deliver. */
export function ProjectHome({ projectId }: { projectId: string }) {
  const router = useRouter();
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setProject(await getProject(projectId));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [projectId]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- loading data on mount
    void load();
  }, [load]);

  const importing = project?.status === "importing";
  useEffect(() => {
    if (!importing) return;
    const timer = setInterval(() => void load(), 2000);
    return () => clearInterval(timer);
  }, [importing, load]);

  if (error) {
    return (
      <p role="alert" className="flex items-center gap-2 text-sm text-destructive">
        <AlertTriangle className="size-4" aria-hidden="true" />
        {error}
      </p>
    );
  }
  if (!project) {
    return (
      <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" aria-hidden="true" />
        Loading project…
      </p>
    );
  }

  const s = project.summary;
  const languages = Object.entries(s.languages ?? {});

  async function remove() {
    if (!project) return;
    if (!window.confirm(`Delete "${project.name}" from Codewright? Your original source is not touched.`)) return;
    await deleteProject(project.id);
    notifyProjectsChanged();
    router.push("/projects");
  }

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <h1 className="font-heading text-2xl font-semibold tracking-tight">{project.name}</h1>
          <p className="truncate text-sm text-muted-foreground">
            {project.source.kind ?? "empty"}
            {project.source.ref && ` · ${project.source.ref}`}
            {project.branch && ` · branch ${project.branch}`}
          </p>
        </div>
        <StatusBadge status={project.status} />
        {project.status === "ready" && (
          <Link href={`/?project=${project.id}`} className={buttonVariants()}>
            <MessageSquarePlus aria-hidden="true" />
            New chat
          </Link>
        )}
        <Button variant="ghost" size="icon" onClick={() => void remove()} aria-label="Delete project">
          <Trash2 aria-hidden="true" />
        </Button>
      </header>

      {project.status === "failed" && (
        <p role="alert" className="rounded-lg border border-destructive/40 p-3 text-sm text-destructive">
          {project.error}
        </p>
      )}

      {project.unsupported && (
        <p role="note" className="flex items-start gap-2 rounded-lg border border-amber-500/40 p-3 text-sm">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-600" aria-hidden="true" />
          {project.unsupported.message}
        </p>
      )}

      {project.status === "ready" && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>What&apos;s in it</CardTitle>
              <CardDescription>
                {s.files ?? 0} files · {((s.size_bytes ?? 0) / 1024 / 1024).toFixed(1)} MB
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-3 text-sm">
              {languages.length > 0 && <p>{languages.map(([lang, n]) => `${lang} (${n})`).join(" · ")}</p>}
              {s.top_level && <p className="font-mono text-xs text-muted-foreground">{s.top_level.join("  ")}</p>}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <ShieldAlert className="size-4" aria-hidden="true" />
                Secrets found
              </CardTitle>
              <CardDescription>
                {project.secrets.length === 0
                  ? "None found."
                  : "Masked as «secret» before anything reaches the model. Consider rotating them."}
              </CardDescription>
            </CardHeader>
            {project.secrets.length > 0 && (
              <CardContent>
                <ul className="flex max-h-48 flex-col gap-1 overflow-y-auto text-sm">
                  {project.secrets.map((f, i) => (
                    <li key={i} className="flex gap-2">
                      <code className="truncate">
                        {f.path}
                        {f.line > 0 && `:${f.line}`}
                      </code>
                      <span className="shrink-0 text-muted-foreground">{f.kind}</span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            )}
          </Card>

          <Instructions project={project} onSaved={load} />
          <Memory project={project} onChanged={load} />

          <Card className="lg:col-span-2">
            <CardHeader>
              <CardTitle>Graph</CardTitle>
              <CardDescription>
                How the modules depend on each other.{" "}
                <Link href={`/projects/${project.id}/graph`} className="underline underline-offset-2">
                  Open the explorer
                </Link>
              </CardDescription>
            </CardHeader>
            <CardContent className="h-96">
              <GraphView projectId={project.id} compact />
            </CardContent>
          </Card>

          <Card className="lg:col-span-2">
            <CardHeader>
              <CardTitle>Sandbox</CardTitle>
              <CardDescription>
                Build, test, lint and run each part in isolated containers: package registries only, no access to this
                machine, previews on localhost.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <SandboxPanel projectId={project.id} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Chats</CardTitle>
            </CardHeader>
            <CardContent>
              {project.chats.length === 0 ? (
                <p className="text-sm text-muted-foreground">No chats yet.</p>
              ) : (
                <ul className="flex flex-col gap-1 text-sm">
                  {project.chats.map((c) => (
                    <li key={c.id}>
                      <Link href={`/c/${c.id}`} className="hover:underline">
                        {c.title}
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Deliver</CardTitle>
              <CardDescription>Send the project&apos;s current files where you want them.</CardDescription>
            </CardHeader>
            <CardContent>
              <DeliverPanel
                projectId={project.id}
                githubRepo={project.source.kind === "github" ? project.source.ref : undefined}
              />
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}

function Instructions({ project, onSaved }: { project: ProjectDetail; onSaved: () => Promise<void> }) {
  const [text, setText] = useState(project.instructions);
  const [saving, setSaving] = useState(false);
  const changed = text !== project.instructions;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Instructions</CardTitle>
        <CardDescription>Codewright follows these in every chat about this project.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        <Textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={4}
          aria-label="Project instructions"
          placeholder="e.g. Keep the Gin router; write tests with testify."
        />
        <div>
          <Button
            size="sm"
            disabled={!changed || saving}
            onClick={async () => {
              setSaving(true);
              await patchProject(project.id, { instructions: text });
              await onSaved();
              setSaving(false);
            }}
          >
            {saving ? "Saving…" : "Save"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function Memory({ project, onChanged }: { project: ProjectDetail; onChanged: () => Promise<void> }) {
  const [key, setKey] = useState("");
  const [value, setValue] = useState("");
  return (
    <Card>
      <CardHeader>
        <CardTitle>Memory</CardTitle>
        <CardDescription>Facts Codewright keeps about this project.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {project.memory.length > 0 && (
          <ul className="flex flex-col gap-1 text-sm">
            {project.memory.map((m) => (
              <li key={m.id} className="flex items-center gap-2">
                <span className="font-medium">{m.key}:</span>
                <span className="min-w-0 flex-1 truncate">{m.value}</span>
                <Button
                  size="icon-sm"
                  variant="ghost"
                  aria-label={`Forget ${m.key}`}
                  onClick={async () => {
                    await deleteMemory(project.id, m.id);
                    await onChanged();
                  }}
                >
                  <X aria-hidden="true" />
                </Button>
              </li>
            ))}
          </ul>
        )}
        <form
          className="flex gap-2"
          onSubmit={async (e) => {
            e.preventDefault();
            if (!key.trim() || !value.trim()) return;
            await addMemory(project.id, key.trim(), value.trim());
            setKey("");
            setValue("");
            await onChanged();
          }}
        >
          <Input
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder="Fact"
            aria-label="Fact"
            className="w-32"
          />
          <Input value={value} onChange={(e) => setValue(e.target.value)} placeholder="Value" aria-label="Value" />
          <Button type="submit" size="sm" variant="outline" disabled={!key.trim() || !value.trim()}>
            Add
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
