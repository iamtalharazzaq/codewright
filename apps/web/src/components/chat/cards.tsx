"use client";

import { CheckCircle2, ExternalLink, Loader2, XCircle } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { Markdown } from "@/components/chat/markdown";
import { DeliverPanel } from "@/components/projects/deliver-panel";
import { StatusBadge } from "@/components/status-badge";
import { Badge } from "@/components/ui/badge";
import { FormSelect } from "@/components/form-select";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { answerConfirm, answerRun, getRun, type ChatMessage, type Question, type RunDetail } from "@/lib/api";
import { cn } from "@/lib/utils";

const CARD = "my-1 flex flex-col gap-3 rounded-xl border bg-card p-4";

/** The option a question's default points at ("Python" for "Python (recommended)"), if any. */
function defaultOption(q: Question): string | undefined {
  const d = q.default.toLowerCase();
  return q.options.find((o) => d === o.toLowerCase()) ?? q.options.find((o) => d.startsWith(o.toLowerCase()));
}

/**
 * Questions from the missing-info check: pick-one questions as a dropdown (the default pre-selected and marked
 * "Recommended"), the others as a short text box. One click sends all answers; "Use the defaults" skips them.
 */
export function QuestionsCard({
  message,
  canAnswer,
  onSend,
}: {
  message: ChatMessage;
  canAnswer: boolean;
  onSend: (text: string) => void;
}) {
  const questions = message.data.questions ?? [];
  const [answers, setAnswers] = useState<string[]>(() => questions.map((q) => defaultOption(q) ?? ""));
  if (questions.length === 0) return <Markdown>{message.content}</Markdown>;

  const set = (i: number, value: string) => setAnswers((prev) => prev.map((a, j) => (j === i ? value : a)));
  const send = () => onSend(questions.map((q, i) => `${q.question} ${answers[i].trim() || q.default}`).join("\n"));

  return (
    <div className={CARD}>
      <p className="text-sm font-medium">Before I start, a few quick questions</p>
      <ol className="grid grid-cols-1 gap-x-4 gap-y-4 sm:grid-cols-2">
        {questions.map((q, i) => {
          const recommended = defaultOption(q);
          return (
            <li key={q.question} className={cn("flex flex-col gap-2", q.options.length === 0 && "sm:col-span-2")}>
              <p className="text-sm">
                <span className="text-muted-foreground">{i + 1}.</span> {q.question}
              </p>
              {q.options.length > 0 ? (
                <FormSelect
                  id={`question-${i}`}
                  value={answers[i]}
                  disabled={!canAnswer}
                  placeholder="Choose one"
                  options={q.options.map((o) => ({ value: o, label: o === recommended ? `${o} (Recommended)` : o }))}
                  onChange={(v) => set(i, v)}
                />
              ) : (
                <Input
                  aria-label={q.question}
                  value={answers[i]}
                  disabled={!canAnswer}
                  placeholder={`Default: ${q.default}`}
                  onChange={(e) => set(i, e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && canAnswer && send()}
                  className="h-9"
                />
              )}
              {q.hint && <p className="text-xs text-muted-foreground">{q.hint}</p>}
            </li>
          );
        })}
      </ol>
      {canAnswer && (
        <div className="flex flex-wrap gap-2">
          <Button size="sm" onClick={send}>
            Send answers
          </Button>
          <Button size="sm" variant="outline" onClick={() => onSend("Defaults are fine.")}>
            Use the defaults
          </Button>
        </div>
      )}
    </div>
  );
}

/** "Here's what I'll make" with [Start] [Change something] (Section 3.4). Nothing is made before Start. */
export function ConfirmCard({ message, onChange }: { message: ChatMessage; onChange: () => void }) {
  const card = message.data.card;
  const state = message.data.state ?? "open";
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!card) return <Markdown>{message.content}</Markdown>;

  async function choose(choice: "start" | "change") {
    setBusy(true);
    setError(null);
    try {
      await answerConfirm(message.conversation_id, message.id, choice);
      if (choice === "change") onChange();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={CARD}>
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-medium">Here&apos;s what I&apos;ll make</p>
        {message.data.label && <Badge variant="secondary">{message.data.label}</Badge>}
      </div>
      <p>{card.what}</p>
      <dl className="grid gap-2 text-sm sm:grid-cols-[6rem_1fr]">
        <dt className="text-muted-foreground">Stack</dt>
        <dd>{card.stack}</dd>
        <dt className="text-muted-foreground">Features</dt>
        <dd>
          <ul className="list-disc pl-4">
            {card.features.map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
        </dd>
        <dt className="text-muted-foreground">You get</dt>
        <dd>{card.deliver}</dd>
      </dl>
      {state === "open" ? (
        <div className="flex gap-2">
          <Button size="sm" disabled={busy} onClick={() => void choose("start")}>
            {busy && <Loader2 className="animate-spin" aria-hidden="true" />}
            Start
          </Button>
          <Button size="sm" variant="outline" disabled={busy} onClick={() => void choose("change")}>
            Change something
          </Button>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">
          {state === "started"
            ? "Started."
            : state === "changing"
              ? "Tell me what to change."
              : state === "replaced"
                ? "Replaced by a new request below."
                : "Changed below."}
        </p>
      )}
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}

/** A run started from the chat: status, current step and the open approval. The run page has the details. */
export function RunCard({ runId, tick }: { runId: string; tick: number }) {
  const [run, setRun] = useState<RunDetail | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void getRun(runId).then(setRun);
    // Poll while it runs: step changes don't reach the chat's event stream, only status changes do.
    const timer = setInterval(() => void getRun(runId).then(setRun), 3000);
    return () => clearInterval(timer);
  }, [runId, tick]);

  if (!run) return <div className={CARD}>Loading run…</div>;
  const gate = run.status === "waiting" && run.pending?.kind === "gate" ? run.pending : null;
  const done = run.plan.filter((p) => p.status === "done").length;

  async function decide(decision: "approve" | "reject") {
    setBusy(true);
    try {
      await answerRun(runId, { decision });
      setRun(await getRun(runId));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={CARD}>
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-medium">Working on it</p>
        <StatusBadge status={run.status} />
      </div>
      {run.plan.length > 0 && (
        <p className="text-sm text-muted-foreground">
          {done} of {run.plan.length} steps done
          {run.current_step
            ? ` · now: ${run.plan.find((p) => p.id === run.current_step)?.title ?? run.current_step}`
            : ""}
        </p>
      )}
      {gate && (
        <div className="flex flex-col gap-2 rounded-lg bg-muted/50 p-3">
          <p className="text-sm font-medium">{gate.title}</p>
          <p className="text-sm text-muted-foreground">{gate.question}</p>
          <div className="flex gap-2">
            <Button size="sm" disabled={busy} onClick={() => void decide("approve")}>
              Approve
            </Button>
            <Button size="sm" variant="outline" disabled={busy} onClick={() => void decide("reject")}>
              Reject
            </Button>
          </div>
        </div>
      )}
      {run.status === "waiting" && !gate && <p className="text-sm">The run needs your answer on the run page.</p>}
      <Link href={`/runs/${run.id}`} className="flex items-center gap-1 text-sm text-primary hover:underline">
        Open the run <ExternalLink className="size-3.5" aria-hidden="true" />
      </Link>
    </div>
  );
}

/** Done card (Section 3.5): what was done, what changed, the guide and next steps. */
export function DoneCard({ message, onSend }: { message: ChatMessage; onSend: (text: string) => void }) {
  const { summary, changed = [], proof = [], guide, suggestions = [], passed = true } = message.data;
  // The first line is the headline; a run's own summary (score, top findings, risks) follows as Markdown.
  const [headline, ...rest] = (summary ?? message.content).split("\n\n");
  const details = rest.join("\n\n");
  return (
    <div className={cn(CARD, !passed && "border-destructive/30")}>
      <p className={cn("flex items-center gap-2 font-medium", !passed && "text-destructive")}>
        {passed ? (
          <CheckCircle2 className="size-4 text-success" aria-hidden="true" />
        ) : (
          <XCircle className="size-4 text-destructive" aria-hidden="true" />
        )}
        {headline}
      </p>
      {details && (
        <div className="text-sm">
          <Markdown>{details}</Markdown>
        </div>
      )}
      {changed.length > 0 && (
        <div className="text-sm">
          <p className="text-muted-foreground">What changed</p>
          <ul className="list-disc pl-5 font-mono text-xs">
            {changed.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </div>
      )}
      {proof.length > 0 && (
        <ul className="text-sm text-muted-foreground">
          {proof.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      )}
      {guide && (
        <details className="text-sm">
          <summary className="cursor-pointer text-muted-foreground">Guide</summary>
          <Markdown>{guide}</Markdown>
        </details>
      )}
      {message.data.playbook === "new_app" && message.run_id && (
        <details open className="text-sm">
          <summary className="cursor-pointer text-muted-foreground">Where should I keep it?</summary>
          <div className="pt-2">
            <DeliverPanel runId={message.run_id} />
          </div>
        </details>
      )}
      {suggestions.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {suggestions.map((s) => (
            <Button key={s} size="sm" variant="outline" className="rounded-full font-normal" onClick={() => onSend(s)}>
              {s}
            </Button>
          ))}
        </div>
      )}
    </div>
  );
}
