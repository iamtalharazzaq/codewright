"use client";

import { useEffect, useId, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { createProject, getConnectors, notifyProjectsChanged, type Connectors, type SourceKind } from "@/lib/api";
import { cn } from "@/lib/utils";

const SOURCES: { kind: SourceKind; label: string; hint: string }[] = [
  { kind: "github", label: "GitHub", hint: "Public repos work as is; private ones need GITHUB_TOKEN in .env." },
  { kind: "zip", label: "ZIP file", hint: "Unsafe archives (paths outside the folder, links, ZIP bombs) are refused." },
  { kind: "local", label: "Local folder", hint: "A folder inside LOCAL_SOURCE_DIR (read-only for Codewright)." },
  { kind: "drive", label: "Google Drive", hint: "A share link to a ZIP file. Connect Drive in Settings first." },
  { kind: "empty", label: "Empty", hint: "Start from nothing; Codewright creates the files." },
];

/** New project (CODEWRIGHT.md Section 2.3): pick a source, give the link/file/folder, done. */
export function NewProjectForm({ onCreated, onCancel }: { onCreated: () => void; onCancel?: () => void }) {
  const id = useId();
  const [kind, setKind] = useState<SourceKind>("github");
  const [ref, setRef] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [connectors, setConnectors] = useState<Connectors | null>(null);

  useEffect(() => {
    getConnectors()
      .then(setConnectors)
      .catch(() => setConnectors(null));
  }, []);

  const source = SOURCES.find((s) => s.kind === kind)!;
  const ready = kind === "empty" ? name.trim() : kind === "zip" ? file : ref.trim();

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await createProject({ kind, name: name.trim(), ref: ref.trim(), file: file ?? undefined });
      notifyProjectsChanged();
      onCreated();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>New project</CardTitle>
        <CardDescription>Codewright works on a copy; your original is never changed.</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit} className="flex flex-col gap-4">
          <div role="radiogroup" aria-label="Source" className="flex flex-wrap gap-2">
            {SOURCES.map((s) => (
              <Button
                key={s.kind}
                type="button"
                role="radio"
                aria-checked={kind === s.kind}
                variant={kind === s.kind ? "default" : "outline"}
                size="sm"
                onClick={() => {
                  setKind(s.kind);
                  setRef("");
                  setError(null);
                }}
              >
                {s.label}
              </Button>
            ))}
          </div>

          {kind === "github" && (
            <Field id={`${id}-ref`} label="Repository URL">
              <Input
                id={`${id}-ref`}
                value={ref}
                onChange={(e) => setRef(e.target.value)}
                placeholder="https://github.com/owner/repo"
              />
            </Field>
          )}
          {kind === "zip" && (
            <Field id={`${id}-file`} label="ZIP file">
              <Input
                id={`${id}-file`}
                type="file"
                accept=".zip,application/zip"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
            </Field>
          )}
          {kind === "local" && (
            <Field id={`${id}-ref`} label="Folder">
              {connectors && connectors.local_folders.length > 0 ? (
                <div className="flex flex-wrap gap-2">
                  {connectors.local_folders.map((f) => (
                    <Button
                      key={f}
                      type="button"
                      size="sm"
                      variant={ref === f ? "default" : "outline"}
                      onClick={() => setRef(f)}
                    >
                      {f}
                    </Button>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">
                  No folders found. Put one in the shared local folder (LOCAL_SOURCE_DIR, default{" "}
                  <code>local-source/</code>).
                </p>
              )}
            </Field>
          )}
          {kind === "drive" && (
            <Field id={`${id}-ref`} label="Drive link to a ZIP">
              <Input
                id={`${id}-ref`}
                value={ref}
                onChange={(e) => setRef(e.target.value)}
                placeholder="https://drive.google.com/file/d/…"
              />
              {connectors && !connectors.drive.connected && (
                <p className="text-xs text-destructive">Google Drive isn&apos;t connected: connect it in Settings.</p>
              )}
            </Field>
          )}
          <Field id={`${id}-name`} label={kind === "empty" ? "Name" : "Name (optional)"}>
            <Input id={`${id}-name`} value={name} onChange={(e) => setName(e.target.value)} placeholder="goshop" />
          </Field>
          <p className={cn("text-xs text-muted-foreground")}>{source.hint}</p>

          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <div className="flex gap-2">
            <Button type="submit" disabled={!ready || busy}>
              {busy ? "Connecting…" : kind === "empty" ? "Create" : "Connect"}
            </Button>
            {onCancel && (
              <Button type="button" variant="ghost" onClick={onCancel}>
                Cancel
              </Button>
            )}
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

function Field({ id, label, children }: { id: string; label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      {children}
    </div>
  );
}
