"use client";

import { PanelRight } from "lucide-react";
import { useState } from "react";

import { Composer } from "@/components/chat/composer";
import { SidePanel } from "@/components/chat/side-panel";
import { Button } from "@/components/ui/button";
import { useMediaQuery } from "@/lib/use-media-query";
import { cn } from "@/lib/utils";

// Examples from README Section 1.2: one per kind of work, so the empty chat shows the range.
const SUGGESTIONS = [
  "What's a saga pattern?",
  "How does checkout work in my project?",
  "Login returns 500, fix it",
  "Create a clinic appointment booking app",
];

type PanelMode = "auto" | "open" | "closed";

/**
 * The main chat screen (README Section 2.1): conversation in the middle, artifacts panel on the right.
 * Phase 0 is the layout only; streaming replies, conversations and approval cards arrive in Phase 2.
 */
export function ChatView() {
  const [draft, setDraft] = useState("");
  // "auto": shown beside the chat on wide screens, hidden on small ones. A toggle makes it explicit.
  const [panel, setPanel] = useState<PanelMode>("auto");
  const wide = useMediaQuery("(min-width: 64rem)");
  const panelVisible = panel === "open" || (panel === "auto" && wide);

  return (
    <div className="flex h-full min-h-0">
      <section aria-label="Chat" className="flex min-w-0 flex-1 flex-col">
        <header className="flex shrink-0 items-center gap-2 border-b px-4 py-2.5">
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-sm font-medium">New chat</h1>
            <p className="truncate text-xs text-muted-foreground">No project · general software questions</p>
          </div>
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
                  <Button variant="outline" size="sm" className="rounded-full font-normal" onClick={() => setDraft(s)}>
                    {s}
                  </Button>
                </li>
              ))}
            </ul>
          </div>
        </div>

        <div className="mx-auto w-full max-w-3xl shrink-0 px-4 pb-4">
          <Composer
            value={draft}
            onChange={setDraft}
            onSend={() => {}}
            disabledReason="Chat replies arrive in Phase 2. The layout is ready."
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
        <SidePanel onClose={() => setPanel("closed")} />
      </aside>
    </div>
  );
}
