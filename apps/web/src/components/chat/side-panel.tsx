"use client";

import {
  ClipboardList,
  FileDiff,
  FileText,
  FlaskConical,
  Monitor,
  Network,
  Workflow,
  X,
  type LucideIcon,
} from "lucide-react";
import { useState } from "react";

import { GraphView } from "@/components/graph/graph-view";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

export const PANEL_TABS: Array<{ id: string; label: string; icon: LucideIcon; empty: string }> = [
  { id: "plan", label: "Plan", icon: ClipboardList, empty: "The plan and its live checklist appear here." },
  { id: "diff", label: "Diff", icon: FileDiff, empty: "Code changes appear here for review before approval." },
  { id: "graph", label: "Graph", icon: Network, empty: "The project's live Graphify graph appears here." },
  { id: "diagram", label: "Diagram", icon: Workflow, empty: "Architecture, flow and sequence diagrams appear here." },
  { id: "tests", label: "Tests", icon: FlaskConical, empty: "Test, replay and benchmark results appear here." },
  {
    id: "preview",
    label: "Preview",
    icon: Monitor,
    empty: "A running preview of the app from the sandbox appears here.",
  },
  { id: "report", label: "Report", icon: FileText, empty: "Audits, verification and final reports appear here." },
];

/**
 * The artifacts panel beside the chat (CODEWRIGHT.md Section 2.2). In a project chat the Graph tab shows the live
 * project graph, with the modules the last reply mentions highlighted; other tabs fill as playbooks produce artifacts.
 */
export function SidePanel({
  onClose,
  projectId = null,
  highlight = [],
}: {
  onClose: () => void;
  projectId?: string | null;
  highlight?: string[];
}) {
  const [tab, setTab] = useState(projectId ? "graph" : "plan");
  const active = PANEL_TABS.find((t) => t.id === tab) ?? PANEL_TABS[0];
  return (
    <Tabs value={tab} onValueChange={(v) => setTab(String(v))} className="flex h-full min-h-0 flex-col gap-0">
      <div className="flex h-14 items-center justify-between gap-2 border-b px-4">
        <h2 className="text-sm font-medium">{active.label}</h2>
        <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="Close side panel">
          <X aria-hidden="true" />
        </Button>
      </div>
      {/* Seven equal icon tabs fill the width, so nothing scrolls or wraps; each has a tooltip and a screen-reader
          name, and the heading above names the active one. */}
      <TabsList
        aria-label="Artifacts"
        className="grid h-10 w-full grid-cols-7 rounded-none border-b bg-transparent p-1"
      >
        {PANEL_TABS.map(({ id, label, icon: Icon }) => (
          <TabsTrigger
            key={id}
            value={id}
            aria-label={label}
            title={label}
            className="h-full rounded-md data-active:bg-muted data-active:text-foreground"
          >
            <Icon aria-hidden="true" />
          </TabsTrigger>
        ))}
      </TabsList>
      {projectId && (
        <TabsContent value="graph" className="min-h-0 flex-1">
          <GraphView projectId={projectId} compact highlight={highlight} />
        </TabsContent>
      )}
      {PANEL_TABS.filter((t) => !(projectId && t.id === "graph")).map(({ id, icon: Icon, empty }) => (
        <TabsContent key={id} value={id} className="min-h-0 flex-1 overflow-y-auto p-6">
          <div className="flex h-full flex-col items-center justify-center gap-3 text-center text-muted-foreground">
            <span className="flex size-10 items-center justify-center rounded-full bg-muted">
              <Icon className="size-4" aria-hidden="true" />
            </span>
            <p className="max-w-60 text-sm">{empty}</p>
          </div>
        </TabsContent>
      ))}
    </Tabs>
  );
}
