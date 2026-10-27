"use client";

import { AlertTriangle, FolderGit2, Loader2, Plus } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { NewProjectForm } from "@/components/projects/new-project-form";
import { StatusBadge } from "@/components/projects/project-status";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { listProjects, PROJECTS_CHANGED, type Project } from "@/lib/api";

type State = { kind: "loading" } | { kind: "error"; message: string } | { kind: "ready"; projects: Project[] };

export function ProjectsView() {
  const [state, setState] = useState<State>({ kind: "loading" });
  const [adding, setAdding] = useState(false);

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      setState({ kind: "ready", projects: await listProjects(signal) });
    } catch (err) {
      if (signal?.aborted) return;
      setState({ kind: "error", message: err instanceof Error ? err.message : String(err) });
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const refresh = () => void load(controller.signal);
    refresh();
    window.addEventListener(PROJECTS_CHANGED, refresh);
    return () => {
      controller.abort();
      window.removeEventListener(PROJECTS_CHANGED, refresh);
    };
  }, [load]);

  // Imports run in the background: poll while one is still going.
  const importing = state.kind === "ready" && state.projects.some((p) => p.status === "importing");
  useEffect(() => {
    if (!importing) return;
    const timer = setInterval(() => void load(), 2000);
    return () => clearInterval(timer);
  }, [importing, load]);

  if (state.kind === "loading") {
    return (
      <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" aria-hidden="true" />
        Loading projects…
      </p>
    );
  }

  if (state.kind === "error") {
    return (
      <Card role="alert">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <AlertTriangle className="size-4 text-destructive" aria-hidden="true" />
            Can&apos;t reach the Codewright API
          </CardTitle>
          <CardDescription>
            Check that the <code>api</code> service is running (<code>docker compose ps</code>). Details:{" "}
            {state.message}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button variant="outline" onClick={() => void load()}>
            Try again
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {adding || state.projects.length === 0 ? (
        <NewProjectForm
          onCancel={state.projects.length > 0 ? () => setAdding(false) : undefined}
          onCreated={() => {
            setAdding(false);
            void load();
          }}
        />
      ) : (
        <div>
          <Button onClick={() => setAdding(true)}>
            <Plus aria-hidden="true" />
            New project
          </Button>
        </div>
      )}
      {state.projects.length > 0 && (
        <ul className="grid gap-4 sm:grid-cols-2">
          {state.projects.map((p) => (
            <li key={p.id}>
              <Link
                href={`/projects/${p.id}`}
                className="block rounded-xl focus-visible:ring-3 focus-visible:ring-ring/50"
              >
                <Card className="transition-colors hover:bg-muted/40">
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2">
                      <FolderGit2 className="size-4 text-muted-foreground" aria-hidden="true" />
                      <span className="truncate">{p.name}</span>
                    </CardTitle>
                    <CardDescription>
                      {p.source.kind ?? "empty"}
                      {p.summary.files !== undefined && ` · ${p.summary.files} files`}
                      {p.summary.languages && ` · ${Object.keys(p.summary.languages).slice(0, 3).join(", ")}`}
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="flex items-center gap-2">
                    <StatusBadge status={p.status} />
                    {p.error && <span className="truncate text-xs text-destructive">{p.error}</span>}
                  </CardContent>
                </Card>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
