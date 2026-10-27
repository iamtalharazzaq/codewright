"use client";

import { useEffect, useId, useState } from "react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { deliver, getConnectors, type Connectors, type DeliverTarget, type DeliveryResult } from "@/lib/api";

const TARGETS: { target: DeliverTarget; label: string }[] = [
  { target: "zip", label: "Download as ZIP" },
  { target: "local", label: "Copy to my deliveries folder" },
  { target: "github", label: "GitHub pull request" },
  { target: "drive", label: "Upload to Google Drive" },
];

/** Deliver (CODEWRIGHT.md C7): the user picks where; one result line per target. */
export function DeliverPanel({
  projectId,
  runId,
  githubRepo,
}: {
  projectId?: string;
  runId?: string;
  githubRepo?: string;
}) {
  const id = useId();
  const [picked, setPicked] = useState<DeliverTarget[]>(["zip"]);
  const [repo, setRepo] = useState(githubRepo ?? "");
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState<DeliveryResult[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [connectors, setConnectors] = useState<Connectors | null>(null);

  useEffect(() => {
    getConnectors()
      .then(setConnectors)
      .catch(() => setConnectors(null));
  }, []);

  function unavailable(target: DeliverTarget): string | null {
    if (!connectors) return null;
    if (target === "github" && !connectors.github_token) return "needs GITHUB_TOKEN in .env";
    if (target === "drive" && !connectors.drive.connected) return "connect Drive in Settings";
    if (target === "local" && !connectors.output_folder) return "set ALLOWED_OUTPUT_DIRS in .env";
    return null;
  }

  async function run() {
    setBusy(true);
    setError(null);
    setResults(null);
    try {
      setResults(
        await deliver({
          targets: picked,
          project_id: projectId,
          run_id: runId,
          github_repo: picked.includes("github") && repo.trim() ? repo.trim() : undefined,
        }),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <ul className="flex flex-col gap-2">
        {TARGETS.map(({ target, label }) => {
          const why = unavailable(target);
          return (
            <li key={target} className="flex items-center gap-2">
              <Checkbox
                id={`${id}-${target}`}
                checked={picked.includes(target)}
                onCheckedChange={(c) => setPicked((p) => (c ? [...p, target] : p.filter((t) => t !== target)))}
              />
              <Label htmlFor={`${id}-${target}`} className="font-normal">
                {label}
                {why && <span className="text-xs text-muted-foreground">({why})</span>}
              </Label>
            </li>
          );
        })}
      </ul>
      {picked.includes("github") && (
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${id}-repo`}>Repository</Label>
          <Input
            id={`${id}-repo`}
            value={repo}
            onChange={(e) => setRepo(e.target.value)}
            placeholder="https://github.com/owner/repo"
          />
        </div>
      )}
      <div>
        <Button onClick={() => void run()} disabled={busy || picked.length === 0}>
          {busy ? "Delivering…" : "Deliver"}
        </Button>
      </div>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {results && (
        <ul aria-label="Delivery results" className="flex flex-col gap-1 text-sm">
          {results.map((r) => (
            <li key={r.target} className={r.ok ? "" : "text-destructive"}>
              <span className="font-medium">{TARGETS.find((t) => t.target === r.target)?.label}:</span>{" "}
              {r.ok ? (
                r.location?.startsWith("http") || r.location?.startsWith("/api/") ? (
                  <a href={r.location} className="underline underline-offset-2" target="_blank" rel="noreferrer">
                    {r.detail ?? r.location}
                  </a>
                ) : (
                  <>
                    {r.detail} <code>{r.location}</code>
                  </>
                )
              ) : (
                r.error
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
