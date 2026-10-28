"use client";

import { Check, Network, Sparkles, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Markdown } from "@/components/chat/markdown";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import type { ChatMessage, GraphFact, SkillRef } from "@/lib/api";

const CARD = "my-1 flex flex-col gap-3 rounded-xl border bg-card p-4";

export type ResolveBody = { action: "save" | "discard"; markdown?: string; project_id?: string | null };

const VERB: Record<GraphFact["relation"], string> = {
  calls: "calls",
  uses: "uses",
  depends_on: "depends on",
  not_calls: "does not call",
};

/** A correction about the architecture, as facts to save on the project graph (USER_FACT) or discard. */
export function CorrectionCard({
  message,
  onResolve,
}: {
  message: ChatMessage;
  onResolve: (id: string, body: ResolveBody) => void;
}) {
  const facts = (message.data.facts as GraphFact[] | undefined) ?? [];
  const state = message.data.state as string | undefined;
  const projectId = message.data.project_id as string | undefined;
  return (
    <div className={CARD}>
      <p className="flex items-center gap-2 text-sm font-medium">
        <Network className="size-4 text-muted-foreground" aria-hidden="true" />
        Correct the project graph
      </p>
      <ul className="flex flex-col gap-1 text-sm">
        {facts.map((f) => (
          <li key={`${f.source}-${f.target}`}>
            <code className="text-xs">{f.source}</code> {VERB[f.relation] ?? f.relation}{" "}
            <code className="text-xs">{f.target}</code>
          </li>
        ))}
      </ul>
      {state === "open" ? (
        <div className="flex flex-wrap gap-2">
          <Button size="sm" onClick={() => onResolve(message.id, { action: "save" })}>
            <Check aria-hidden="true" />
            Save as fact
          </Button>
          <Button size="sm" variant="ghost" onClick={() => onResolve(message.id, { action: "discard" })}>
            Discard
          </Button>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">
          {state === "saved" ? (
            <>
              Saved. The graph now shows {facts.length === 1 ? "it" : "them"} as your facts
              {projectId && (
                <>
                  {" "}
                  (
                  <Link href={`/projects/${projectId}/graph`} className="underline underline-offset-2">
                    open the graph
                  </Link>
                  )
                </>
              )}
              .
            </>
          ) : (
            "Discarded."
          )}
        </p>
      )}
    </div>
  );
}

/** A drafted custom skill: shown as its SKILL.md, editable, saved globally or for this project only on approval. */
export function SkillDraftCard({
  message,
  projectId,
  onResolve,
}: {
  message: ChatMessage;
  projectId: string | null;
  onResolve: (id: string, body: ResolveBody) => void;
}) {
  const [markdown, setMarkdown] = useState(String(message.data.markdown ?? ""));
  const [editing, setEditing] = useState(false);
  const state = message.data.state as string | undefined;
  const saved = message.data.skill as SkillRef | undefined;
  return (
    <div className={CARD}>
      <p className="flex items-center gap-2 text-sm font-medium">
        <Sparkles className="size-4 text-muted-foreground" aria-hidden="true" />
        {message.content}
      </p>
      {editing && state === "open" ? (
        <Textarea
          value={markdown}
          onChange={(e) => setMarkdown(e.target.value)}
          rows={16}
          className="font-mono text-xs"
          aria-label="Skill (SKILL.md)"
        />
      ) : (
        <div className="max-h-80 overflow-y-auto rounded-lg bg-muted/50 p-3 text-sm">
          <Markdown>{"```markdown\n" + markdown + "\n```"}</Markdown>
        </div>
      )}
      {state === "open" ? (
        <div className="flex flex-wrap gap-2">
          <Button size="sm" onClick={() => onResolve(message.id, { action: "save", markdown })}>
            <Check aria-hidden="true" />
            Save for all projects
          </Button>
          {projectId && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => onResolve(message.id, { action: "save", markdown, project_id: projectId })}
            >
              Save for this project
            </Button>
          )}
          <Button size="sm" variant="outline" onClick={() => setEditing((e) => !e)}>
            {editing ? "Preview" : "Edit"}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => onResolve(message.id, { action: "discard" })}>
            Discard
          </Button>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">
          {state === "saved" && saved ? (
            <>
              Saved. Use it with <code>{saved.command}</code>, or manage it on the{" "}
              <Link href="/skills" className="underline underline-offset-2">
                Skills
              </Link>{" "}
              screen.
            </>
          ) : (
            "Discarded."
          )}
        </p>
      )}
    </div>
  );
}

/** "Using skill: X" on a reply; when it was picked automatically, "Run without it" answers again without it. */
export function SkillBadge({ skill, canRerun, onRerun }: { skill: SkillRef; canRerun: boolean; onRerun: () => void }) {
  return (
    <p className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
      <span className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5">
        <Sparkles className="size-3" aria-hidden="true" />
        Using skill: <span className="font-medium text-foreground">{skill.title}</span>
        <span className="font-mono">{skill.command}</span>
      </span>
      {skill.auto && canRerun && (
        <button type="button" onClick={onRerun} className="inline-flex items-center gap-1 hover:text-foreground">
          <X className="size-3" aria-hidden="true" />
          Run without it
        </button>
      )}
    </p>
  );
}
