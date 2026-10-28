"use client";

import { ExternalLink, Monitor, RotateCw, Square, SquareTerminal } from "lucide-react";
import { useState } from "react";

import { TerminalView } from "@/components/sandbox/terminal-view";
import { Button, buttonVariants } from "@/components/ui/button";
import type { Preview } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * Running previews of a project (CODEWRIGHT.md Phase 5): web apps in a frame (served on 127.0.0.1 only), console
 * apps in an interactive terminal. Several can run at once (an API and its frontend); pick one at the top.
 */
export function PreviewView({
  projectId,
  previews,
  onStop,
  empty,
}: {
  projectId: string;
  previews: Preview[];
  onStop: (p: Preview) => Promise<void>;
  empty?: React.ReactNode;
}) {
  const [chosen, setChosen] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const current = previews.find((p) => p.id === chosen) ?? previews.at(-1);

  if (!current) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center text-muted-foreground">
        <span className="flex size-10 items-center justify-center rounded-full bg-muted">
          <Monitor className="size-4" aria-hidden="true" />
        </span>
        <div className="max-w-64 text-sm">{empty ?? "Run the project to see it here."}</div>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-2">
      <div className="flex flex-wrap items-center gap-1.5">
        {previews.length > 1 &&
          previews.map((p) => (
            <Button
              key={p.id}
              size="xs"
              variant={p.id === current.id ? "secondary" : "ghost"}
              onClick={() => setChosen(p.id)}
              aria-pressed={p.id === current.id}
            >
              {p.kind === "web" ? <Monitor aria-hidden="true" /> : <SquareTerminal aria-hidden="true" />}
              {p.name}
            </Button>
          ))}
        <span className="min-w-0 flex-1 truncate font-mono text-xs text-muted-foreground" title={current.cmd.join(" ")}>
          {current.url ?? current.cmd.join(" ")}
        </span>
        {!current.running && <span className="text-xs text-destructive">stopped</span>}
        {current.kind === "web" && current.url && (
          <>
            <Button
              size="icon-xs"
              variant="ghost"
              aria-label="Reload preview"
              onClick={() => setReloadKey((k) => k + 1)}
            >
              <RotateCw aria-hidden="true" />
            </Button>
            <a
              href={current.url}
              target="_blank"
              rel="noreferrer"
              aria-label="Open preview in a new tab"
              className={cn(buttonVariants({ size: "icon-xs", variant: "ghost" }))}
            >
              <ExternalLink aria-hidden="true" />
            </a>
          </>
        )}
        <Button size="icon-xs" variant="ghost" aria-label={`Stop ${current.name}`} onClick={() => void onStop(current)}>
          <Square aria-hidden="true" />
        </Button>
      </div>
      {current.kind === "web" && current.url ? (
        <iframe
          key={`${current.id}-${reloadKey}`}
          src={current.url}
          title={`Preview: ${current.name}`}
          className="min-h-64 w-full flex-1 rounded-lg border bg-white"
          sandbox="allow-scripts allow-forms allow-same-origin allow-popups allow-modals"
        />
      ) : (
        <TerminalView key={current.id} projectId={projectId} preview={current} />
      )}
    </div>
  );
}
