"use client";

import { AlertTriangle, FolderPlus, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { listProjects, type Project } from "@/lib/api";

type State = { kind: "loading" } | { kind: "error"; message: string } | { kind: "ready"; projects: Project[] };

export function ProjectsView() {
  const [state, setState] = useState<State>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    listProjects(controller.signal)
      .then((projects) => setState({ kind: "ready", projects }))
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setState({ kind: "error", message: err instanceof Error ? err.message : String(err) });
      });
    return () => controller.abort();
  }, [attempt]);

  function retry() {
    setState({ kind: "loading" });
    setAttempt((n) => n + 1);
  }

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
          <Button variant="outline" onClick={retry}>
            Try again
          </Button>
        </CardContent>
      </Card>
    );
  }

  if (state.projects.length === 0) {
    return (
      <Card className="items-center py-12 text-center">
        <CardHeader className="w-full justify-items-center">
          <span className="mb-2 flex size-12 items-center justify-center rounded-full bg-muted">
            <FolderPlus className="size-5 text-muted-foreground" aria-hidden="true" />
          </span>
          <CardTitle>No projects yet</CardTitle>
          <CardDescription className="max-w-md">
            A project is a codebase Codewright works on. You&apos;ll be able to connect one from GitHub, a ZIP file,
            Google Drive or a local folder, or create a new one from a chat.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button disabled title="Available in Phase 3">
            New project
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <ul className="grid gap-4 sm:grid-cols-2">
      {state.projects.map((p) => (
        <li key={p.id}>
          <Card>
            <CardHeader>
              <CardTitle>{p.name}</CardTitle>
              <CardDescription>Updated {new Date(p.updated_at).toLocaleString()}</CardDescription>
            </CardHeader>
            <CardContent className="flex gap-2">
              <Badge variant="outline">{p.status}</Badge>
            </CardContent>
          </Card>
        </li>
      ))}
    </ul>
  );
}
