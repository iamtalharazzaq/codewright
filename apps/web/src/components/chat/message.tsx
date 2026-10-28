"use client";

import { ChevronLeft, ChevronRight, FileText, Pencil, RotateCcw, Workflow } from "lucide-react";
import { useState } from "react";

import { ConfirmCard, DoneCard, QuestionsCard, RunCard } from "@/components/chat/cards";
import { CopyButton, Markdown } from "@/components/chat/markdown";
import { CorrectionCard, SkillBadge, SkillDraftCard, type ResolveBody } from "@/components/chat/skill-cards";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import type { ChatMessage, DiagramData, SkillRef } from "@/lib/api";

export interface MessageActions {
  onSend: (text: string) => void;
  onEdit: (messageId: string, text: string) => void;
  onRegenerate: (messageId: string, withoutSkill?: boolean) => void;
  onSwitch: (messageId: string) => void;
  onChangeRequested: () => void;
  onResolve: (messageId: string, body: ResolveBody) => void;
  onShowTab: (tab: string) => void;
}

/** One message. User messages can be edited, replies regenerated; ‹ 1/2 › switches between branches. */
export function MessageView({
  message,
  isLast,
  busy,
  runTick,
  actions,
}: {
  message: ChatMessage;
  isLast: boolean;
  busy: boolean;
  runTick: number;
  actions: MessageActions;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(message.content);

  if (message.role === "user") {
    return (
      <div className="group flex flex-col items-end gap-1">
        {editing ? (
          <div className="flex w-full max-w-[85%] flex-col gap-2">
            <Textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={3} aria-label="Edit message" />
            <div className="flex justify-end gap-2">
              <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
                Cancel
              </Button>
              <Button
                size="sm"
                disabled={!draft.trim() || busy}
                onClick={() => {
                  setEditing(false);
                  actions.onEdit(message.id, draft.trim());
                }}
              >
                Send
              </Button>
            </div>
          </div>
        ) : (
          <>
            {message.data.attachments && message.data.attachments.length > 0 && (
              <ul aria-label="Attached files" className="flex max-w-[85%] flex-wrap justify-end gap-1.5">
                {message.data.attachments.map((a) => (
                  <li key={a.id} className="rounded-md border px-2 py-0.5 text-xs text-muted-foreground">
                    {a.filename}
                    {a.secrets > 0 && ` · ${a.secrets} secret${a.secrets > 1 ? "s" : ""} masked`}
                  </li>
                ))}
              </ul>
            )}
            <div className="max-w-[85%] rounded-2xl bg-muted px-4 py-2.5 whitespace-pre-wrap">{message.content}</div>
          </>
        )}
        {!editing && (
          <div className="flex items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
            <Branches message={message} onSwitch={actions.onSwitch} />
            <Button
              variant="ghost"
              size="icon-xs"
              aria-label="Edit message"
              title="Edit"
              disabled={busy}
              onClick={() => {
                setDraft(message.content);
                setEditing(true);
              }}
            >
              <Pencil aria-hidden="true" />
            </Button>
          </div>
        )}
      </div>
    );
  }

  const streaming = message.status === "streaming";
  const skill = message.data.skill as SkillRef | undefined;
  const diagram = message.data.diagram as DiagramData | undefined;
  return (
    <div className="group flex flex-col gap-1">
      {skill && message.kind !== "done" && (
        <SkillBadge skill={skill} canRerun={isLast && !busy} onRerun={() => actions.onRegenerate(message.id, true)} />
      )}
      <Body message={message} isLast={isLast} runTick={runTick} actions={actions} />
      {diagram && !streaming && (
        <button
          type="button"
          onClick={() => actions.onShowTab("diagram")}
          className="inline-flex w-fit items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          <Workflow className="size-3.5" aria-hidden="true" />
          Diagram: {diagram.title}
        </button>
      )}
      {message.kind === "done" && message.run_id && (
        <button
          type="button"
          onClick={() => actions.onShowTab("report")}
          className="inline-flex w-fit items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          <FileText className="size-3.5" aria-hidden="true" />
          Open the report
        </button>
      )}
      {streaming && !message.content && message.kind === "text" && (
        <p className="animate-pulse text-sm text-muted-foreground">Thinking…</p>
      )}
      {message.status === "stopped" && <p className="text-xs text-muted-foreground">Stopped.</p>}
      {!streaming && (message.kind === "text" || message.kind === "error" || message.kind === "decline") && (
        <div className="flex items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
          <Branches message={message} onSwitch={actions.onSwitch} />
          {message.content && <CopyButton text={message.content} label="Copy reply" />}
          {isLast && (
            <Button
              variant="ghost"
              size="icon-xs"
              aria-label="Regenerate reply"
              title="Regenerate"
              disabled={busy}
              onClick={() => actions.onRegenerate(message.id)}
            >
              <RotateCcw aria-hidden="true" />
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

function Body({
  message,
  isLast,
  runTick,
  actions,
}: {
  message: ChatMessage;
  isLast: boolean;
  runTick: number;
  actions: MessageActions;
}) {
  switch (message.kind) {
    case "questions":
      return <QuestionsCard message={message} canAnswer={isLast} onSend={actions.onSend} />;
    case "confirm":
      return <ConfirmCard message={message} onChange={actions.onChangeRequested} />;
    case "run":
      return message.run_id ? <RunCard runId={message.run_id} tick={runTick} /> : null;
    case "done":
      return <DoneCard message={message} onSend={actions.onSend} />;
    case "correction":
      return <CorrectionCard message={message} onResolve={actions.onResolve} />;
    case "skill_draft":
      return (
        <SkillDraftCard
          message={message}
          projectId={(message.data.project_id as string | null | undefined) ?? null}
          onResolve={actions.onResolve}
        />
      );
    case "error":
      return (
        <p
          role="alert"
          className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive"
        >
          {message.content}
        </p>
      );
    default:
      return <Markdown>{message.content}</Markdown>;
  }
}

function Branches({ message, onSwitch }: { message: ChatMessage; onSwitch: (id: string) => void }) {
  const count = message.siblings.length;
  if (count < 2) return null;
  const index = message.siblings.indexOf(message.id);
  return (
    <span className="flex items-center text-xs text-muted-foreground">
      <Button
        variant="ghost"
        size="icon-xs"
        aria-label="Previous version"
        disabled={index <= 0}
        onClick={() => onSwitch(message.siblings[index - 1])}
      >
        <ChevronLeft aria-hidden="true" />
      </Button>
      {index + 1}/{count}
      <Button
        variant="ghost"
        size="icon-xs"
        aria-label="Next version"
        disabled={index >= count - 1}
        onClick={() => onSwitch(message.siblings[index + 1])}
      >
        <ChevronRight aria-hidden="true" />
      </Button>
    </span>
  );
}
