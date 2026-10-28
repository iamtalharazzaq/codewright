"use client";

import { Loader2, Play } from "lucide-react";

import { PreviewView } from "@/components/sandbox/preview-view";
import { useSandbox } from "@/components/sandbox/use-sandbox";
import { Button } from "@/components/ui/button";

/** The Preview tab of a project chat: the project's running previews, or a button to run it in the sandbox. */
export function PreviewTab({ projectId }: { projectId: string }) {
  const sb = useSandbox(projectId);
  const runnable = sb.status?.components.some((c) => c.run) ?? false;
  return (
    <div className="flex h-full min-h-0 flex-col p-3">
      <PreviewView
        projectId={projectId}
        previews={sb.previews}
        onStop={sb.stopOne}
        empty={
          sb.busy ? (
            <p className="flex items-center justify-center gap-2" role="status">
              <Loader2 className="size-4 animate-spin" aria-hidden="true" />
              {sb.log?.steps.at(-1)?.name ?? "Starting"}…
            </p>
          ) : (
            <div className="flex flex-col items-center gap-3">
              <p>
                {runnable ? "Run the project in the sandbox to see it here." : "Nothing in this project can run yet."}
              </p>
              {runnable && (
                <Button size="sm" onClick={() => void sb.start("run")}>
                  <Play aria-hidden="true" />
                  Run app
                </Button>
              )}
              {sb.log?.status === "failed" || sb.log?.status === "error" ? (
                <p className="text-destructive">{sb.log.error ?? "The last run failed; see the project page."}</p>
              ) : null}
            </div>
          )
        }
      />
    </div>
  );
}
