"use client";

import {
  AlertTriangle,
  Check,
  Cpu,
  Gauge,
  Loader2,
  Pencil,
  Play,
  RotateCcw,
  ShieldCheck,
  Square,
  X,
} from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  answerRun,
  PROFILE_LABEL,
  type BudgetPrompt,
  type Choice,
  type Decision,
  type GatePrompt,
  type LLMUnavailablePrompt,
} from "@/lib/api";

/** A gate card: what was decided, the data behind it, and Approve / Edit / Reject (README 9.1). */
export function GateCard({ runId, prompt, onAnswered }: { runId: string; prompt: GatePrompt; onAnswered: () => void }) {
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState<Decision | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function decide(decision: Decision) {
    if (decision !== "approve" && !comment.trim()) {
      setError("Edit and Reject need a comment explaining what to change.");
      return;
    }
    setBusy(decision);
    setError(null);
    try {
      await answerRun(runId, { decision, comment });
      setComment("");
      onAnswered();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card className="ring-2 ring-warning/40" aria-labelledby="gate-title">
      <CardHeader>
        <CardTitle id="gate-title" className="flex items-center gap-2">
          <ShieldCheck className="size-4 text-warning" aria-hidden="true" />
          {prompt.number != null ? `Gate ${prompt.number}: ${prompt.title}` : prompt.title}
          {prompt.subject && <span className="font-mono text-sm text-muted-foreground">({prompt.subject})</span>}
        </CardTitle>
        <CardDescription>{prompt.question}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <details className="rounded-md border bg-muted/40 p-3 text-sm">
          <summary className="cursor-pointer font-medium">What this decision is about</summary>
          <pre className="mt-2 max-h-64 overflow-auto font-mono text-xs whitespace-pre-wrap">
            {JSON.stringify(prompt.summary, null, 2)}
          </pre>
        </details>
        <div className="grid gap-1.5">
          <Label htmlFor="gate-comment">Comment (required for Edit and Reject)</Label>
          <Textarea
            id="gate-comment"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="e.g. Payment also calls Notification"
            rows={3}
          />
        </div>
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
      </CardContent>
      <CardFooter className="flex flex-wrap gap-2">
        <Button onClick={() => void decide("approve")} disabled={busy !== null}>
          {busy === "approve" ? <Loader2 className="animate-spin" aria-hidden="true" /> : <Check aria-hidden="true" />}
          Approve
        </Button>
        <Button variant="outline" onClick={() => void decide("edit")} disabled={busy !== null}>
          <Pencil aria-hidden="true" />
          Edit
        </Button>
        <Button variant="destructive" onClick={() => void decide("reject")} disabled={busy !== null}>
          <X aria-hidden="true" />
          Reject
        </Button>
      </CardFooter>
    </Card>
  );
}

function useChoice(runId: string, onAnswered: () => void) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function choose(choice: Choice) {
    setBusy(true);
    setError(null);
    try {
      await answerRun(runId, { choice });
      onAnswered();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  return { busy, error, choose };
}

/** Shown when a step hits its budget (README Section 8.4): continue with more budget, or stop the run. */
export function BudgetCard({
  runId,
  prompt,
  onAnswered,
}: {
  runId: string;
  prompt: BudgetPrompt;
  onAnswered: () => void;
}) {
  const { busy, error, choose } = useChoice(runId, onAnswered);
  return (
    <Card className="ring-2 ring-warning/40" role="alert">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Gauge className="size-4 text-warning" aria-hidden="true" />
          Budget reached at step {prompt.step}
        </CardTitle>
        <CardDescription>
          {prompt.reason}. The run is paused and saved. Continue doubles the limits once more; Stop ends the run.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <pre className="rounded-md bg-muted p-2 font-mono text-xs whitespace-pre-wrap">
          {JSON.stringify(prompt.used, null, 2)}
        </pre>
        {error && <p className="mt-2 text-sm text-destructive">{error}</p>}
      </CardContent>
      <CardFooter className="flex flex-wrap gap-2">
        <Button onClick={() => void choose("continue")} disabled={busy}>
          <Play aria-hidden="true" />
          Continue
        </Button>
        <Button variant="destructive" onClick={() => void choose("stop")} disabled={busy}>
          <Square aria-hidden="true" />
          Stop run
        </Button>
      </CardFooter>
    </Card>
  );
}

/** Shown when the model server can't be reached (README 8.1: checkpoint, pause and ask). */
export function LLMUnavailableCard({
  runId,
  prompt,
  onAnswered,
}: {
  runId: string;
  prompt: LLMUnavailablePrompt;
  onAnswered: () => void;
}) {
  const { busy, error, choose } = useChoice(runId, onAnswered);

  return (
    <Card className="ring-2 ring-destructive/40" role="alert">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <AlertTriangle className="size-4 text-destructive" aria-hidden="true" />
          {PROFILE_LABEL[prompt.profile]} model server is unavailable
        </CardTitle>
        <CardDescription>
          The run is paused and saved at step <strong>{prompt.step}</strong>. Nothing is lost. Retry when the server is
          back{prompt.options.includes("switch_to_cpu") ? ", or continue on the local CPU (slower)" : ""}. You can also
          leave it paused and come back later.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <p className="rounded-md bg-muted p-2 font-mono text-xs break-all">{prompt.error}</p>
        {error && <p className="mt-2 text-sm text-destructive">{error}</p>}
      </CardContent>
      <CardFooter className="flex flex-wrap gap-2">
        <Button onClick={() => void choose("retry")} disabled={busy}>
          <RotateCcw aria-hidden="true" />
          Retry
        </Button>
        {prompt.options.includes("switch_to_cpu") && (
          <Button variant="outline" onClick={() => void choose("switch_to_cpu")} disabled={busy}>
            <Cpu aria-hidden="true" />
            Switch to local CPU
          </Button>
        )}
      </CardFooter>
    </Card>
  );
}
