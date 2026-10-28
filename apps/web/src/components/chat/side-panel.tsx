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
import { Markdown } from "@/components/chat/markdown";
import { RunReport } from "@/components/chat/run-report";
import { GraphView } from "@/components/graph/graph-view";
import { PreviewTab } from "@/components/sandbox/preview-tab";
import { TestsTab } from "@/components/tests/tests-tab";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { DiagramData } from "@/lib/api";

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

export const defaultTab = (projectId: string | null) => (projectId ? "graph" : "plan");

/**
 * The artifacts panel beside the chat (CODEWRIGHT.md Section 2.2). In a project chat the Graph tab shows the live
 * project graph, with the modules the last reply mentions highlighted, Tests its test runs, coverage and traffic replays,
 * and Preview the project running in the sandbox.
 * Diagram shows the last explanation's diagram, Report the reports of the last run started from the chat. The chat
 * controls the tab, so an explanation can open its diagram and a finished run its report.
 */
export function SidePanel({
  onClose,
  projectId = null,
  highlight = [],
  tab,
  onTabChange,
  diagram = null,
  runId = null,
  runTick = 0,
}: {
  onClose: () => void;
  projectId?: string | null;
  highlight?: string[];
  tab: string;
  onTabChange: (tab: string) => void;
  diagram?: DiagramData | null;
  runId?: string | null;
  runTick?: number;
}) {
  const active = PANEL_TABS.find((t) => t.id === tab) ?? PANEL_TABS[0];
  const filled = new Set<string>([
    ...(projectId ? ["graph", "tests", "preview"] : []),
    ...(diagram ? ["diagram"] : []),
    ...(runId ? ["report"] : []),
  ]);
  return (
    <Tabs value={tab} onValueChange={(v) => onTabChange(String(v))} className="flex h-full min-h-0 flex-col gap-0">
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
      {projectId && (
        <TabsContent value="tests" className="min-h-0 flex-1">
          <TestsTab projectId={projectId} />
        </TabsContent>
      )}
      {projectId && (
        <TabsContent value="preview" className="min-h-0 flex-1">
          <PreviewTab projectId={projectId} />
        </TabsContent>
      )}
      {diagram && (
        <TabsContent value="diagram" className="min-h-0 flex-1 overflow-y-auto p-4">
          <h3 className="pb-2 text-sm font-medium">{diagram.title}</h3>
          <Markdown>{"```mermaid\n" + diagram.mermaid + "\n```"}</Markdown>
        </TabsContent>
      )}
      {runId && (
        <TabsContent value="report" className="min-h-0 flex-1">
          <RunReport runId={runId} tick={runTick} />
        </TabsContent>
      )}
      {PANEL_TABS.filter((t) => !filled.has(t.id)).map(({ id, icon: Icon, empty }) => (
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
