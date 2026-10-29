"use client";

import { PanelRight } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { Composer } from "@/components/chat/composer";
import { MessageView, type MessageActions } from "@/components/chat/message";
import { ModelPicker } from "@/components/chat/model-picker";
import { SidePanel, defaultTab } from "@/components/chat/side-panel";
import { useConversation } from "@/components/chat/use-conversation";
import { Button } from "@/components/ui/button";
import {
  getGraph,
  getProject,
  notifyConversationsChanged,
  type DiagramData,
  regenerateMessage,
  resolveCard,
  sendMessage,
  startConversation,
  stopConversation,
  switchBranch,
} from "@/lib/api";
import { useMediaQuery } from "@/lib/use-media-query";
import { cn } from "@/lib/utils";

// Requests from EXAMPLES.md: a question, a snippet, a small app and a review.
const SUGGESTIONS = [
  "What's a saga pattern?",
  "Write code to reverse a linked list",
  "Make a tic-tac-toe game",
  "/review-code src/",
];

type PanelMode = "auto" | "open" | "closed";

/**
 * The main chat screen (CODEWRIGHT.md Section 2.1): conversation in the middle, artifacts panel on the right.
 * Without `conversationId` it is a new chat; the first message creates the conversation and moves to its URL.
 */
export function ChatView({
  conversationId = null,
  projectId = null,
}: {
  conversationId?: string | null;
  projectId?: string | null;
}) {
  const router = useRouter();
  const [projectName, setProjectName] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const { detail, error: loadError, reload, runTick } = useConversation(conversationId);
  // "auto": shown beside the chat on wide screens, hidden on small ones. A toggle makes it explicit.
  const [panel, setPanel] = useState<PanelMode>("auto");
  const wide = useMediaQuery("(min-width: 64rem)");
  const panelVisible = panel === "open" || (panel === "auto" && wide);
  const bottom = useRef<HTMLDivElement>(null);
  const messages = detail?.messages ?? [];
  const busy = detail?.busy ?? false;
  const lastText = messages.at(-1)?.content.length ?? 0;
  const activeProject = detail?.conversation.project_id ?? projectId;
  // Modules the last reply talks about ("internal/order", "order/service/..."), highlighted in the Graph tab.
  const lastReply = [...messages].reverse().find((m) => m.role === "assistant")?.content ?? "";
  const [modules, setModules] = useState<string[]>([]);
  const lastData = [...messages].reverse().find((m) => m.role === "assistant")?.data;
  const mentioned = useMemo(() => {
    const used = Array.isArray(lastData?.modules) ? (lastData.modules as string[]) : [];
    return [...new Set([...used, ...modules.filter((m) => lastReply.includes(m))])];
  }, [modules, lastReply, lastData]);
  // The last explanation's diagram and the last run started here feed the Diagram and Report tabs.
  const diagramMessage = [...messages].reverse().find((m) => m.data.diagram);
  const diagram = (diagramMessage?.data.diagram as DiagramData | undefined) ?? null;
  const runMessage = [...messages].reverse().find((m) => m.run_id);
  const runId = runMessage?.run_id ?? null;
  const doneId = [...messages].reverse().find((m) => m.kind === "done" && m.run_id)?.id ?? null;
  const [tab, setTab] = useState(defaultTab(activeProject));
  const shown = useRef<{ diagram?: string; done?: string }>({});

  // Open the Diagram tab when an explanation brings a new one, and the Report tab when a run finishes. Messages that
  // were already there when the chat opened don't switch tabs.
  useEffect(() => {
    if (!detail) return;
    const first = shown.current.diagram === undefined && shown.current.done === undefined;
    const newDiagram = diagramMessage && diagramMessage.id !== shown.current.diagram;
    const newDone = doneId && doneId !== shown.current.done;
    shown.current = { diagram: diagramMessage?.id ?? "", done: doneId ?? "" };
    if (first) return;
    if (newDone) setTab("report");
    else if (newDiagram) setTab("diagram");
  }, [detail, diagramMessage, doneId]);

  useEffect(() => {
    if (!activeProject) return;
    getGraph(activeProject)
      .then((g) => setModules(g.graph?.nodes.map((n) => n.id).filter((id) => id.includes("/")) ?? []))
      .catch(() => setModules([]));
  }, [activeProject]);

  useEffect(() => {
    if (!activeProject) return;
    getProject(activeProject)
      .then((p) => setProjectName(p.name))
      .catch(() => setProjectName(null));
  }, [activeProject]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [messages.length, lastText]);

  async function act(fn: () => Promise<unknown>) {
    setError(null);
    try {
      await fn();
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  function send(text: string, attachments: string[] = []) {
    setDraft("");
    if (!conversationId) {
      void act(async () => {
        const res = await startConversation(text, projectId, attachments);
        notifyConversationsChanged();
        router.push(`/c/${res.conversation.id}`);
      });
      return;
    }
    void act(() => sendMessage(conversationId, text, undefined, attachments));
  }

  const actions: MessageActions = {
    onSend: send,
    onEdit: (id, text) => conversationId && void act(() => sendMessage(conversationId, text, id)),
    onRegenerate: (id, withoutSkill) =>
      conversationId && void act(() => regenerateMessage(conversationId, id, withoutSkill)),
    onResolve: (id, body) => conversationId && void act(() => resolveCard(conversationId, id, body)),
    onShowTab: (name) => {
      setTab(name);
      if (!panelVisible) setPanel("open");
    },
    onSwitch: (id) => conversationId && void act(() => switchBranch(conversationId, id)),
    onChangeRequested: () => document.querySelector<HTMLTextAreaElement>("#chat-composer textarea")?.focus(),
  };

  return (
    <div className="flex h-full min-h-0">
      <section aria-label="Chat" className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-2 border-b px-4">
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-sm font-medium">{detail?.conversation.title ?? "New chat"}</h1>
            <p className="truncate text-xs text-muted-foreground">
              {activeProject && projectName ? (
                <Link href={`/projects/${activeProject}`} className="hover:underline">
                  Project · {projectName}
                </Link>
              ) : (
                "No project · general software questions"
              )}
            </p>
          </div>
          <ModelPicker />
          <Button
            variant="ghost"
            size="icon"
            onClick={() => setPanel(panelVisible ? "closed" : "open")}
            aria-label={panelVisible ? "Hide side panel" : "Show side panel"}
            aria-expanded={panelVisible}
            aria-controls="side-panel"
          >
            <PanelRight aria-hidden="true" />
          </Button>
        </header>

        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
          {conversationId ? (
            <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 py-6" aria-live="polite">
              {loadError && (
                <p role="alert" className="text-sm text-destructive">
                  {loadError}
                </p>
              )}
              {messages.map((m, i) => (
                <MessageView
                  key={m.id}
                  message={m}
                  isLast={i === messages.length - 1}
                  busy={busy}
                  runTick={runTick}
                  actions={actions}
                />
              ))}
              <div ref={bottom} />
            </div>
          ) : (
            <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col items-center justify-center gap-6 px-4 py-10 text-center">
              <h2 className="font-heading text-3xl font-semibold tracking-tight text-balance">
                What are we building today?
              </h2>
              <p className="max-w-lg text-sm text-pretty text-muted-foreground">
                Ask anything about software, or connect a project and let the team explain, fix, improve or extend it.
                Nothing changes without your approval.
              </p>
              <ul aria-label="Suggestions" className="flex flex-wrap justify-center gap-2">
                {SUGGESTIONS.map((s) => (
                  <li key={s}>
                    <Button
                      variant="outline"
                      size="sm"
                      className="rounded-full font-normal"
                      onClick={() => setDraft(s)}
                    >
                      {s}
                    </Button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        <div id="chat-composer" className="mx-auto w-full max-w-3xl shrink-0 px-4 pb-4">
          {error && (
            <p role="alert" className="pb-2 text-sm text-destructive">
              {error}
            </p>
          )}
          <Composer
            value={draft}
            onChange={setDraft}
            onSend={send}
            busy={busy}
            onStop={conversationId ? () => void act(() => stopConversation(conversationId)) : undefined}
            projectId={activeProject}
          />
        </div>
      </section>

      <aside
        id="side-panel"
        aria-label="Side panel"
        className={cn(
          "min-h-0 flex-col border-l bg-background",
          panel === "auto" && "hidden lg:flex lg:w-[26rem] lg:shrink-0",
          panel === "open" && "fixed inset-0 z-20 flex lg:static lg:w-[26rem] lg:shrink-0",
          panel === "closed" && "hidden",
        )}
      >
        <SidePanel
          key={activeProject ?? "none"}
          onClose={() => setPanel("closed")}
          projectId={activeProject}
          highlight={mentioned}
          tab={tab}
          onTabChange={setTab}
          diagram={diagram}
          runId={runId}
          runTick={runTick}
          messages={messages}
        />
      </aside>
    </div>
  );
}
