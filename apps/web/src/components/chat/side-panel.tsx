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

/** The artifacts panel beside the chat (README Section 2.2). Tabs are empty until playbooks produce artifacts. */
export function SidePanel({ onClose }: { onClose: () => void }) {
  return (
    <Tabs defaultValue="plan" className="flex h-full min-h-0 flex-col gap-0">
      <div className="flex items-center gap-1 border-b px-2 py-2">
        <div className="min-w-0 flex-1 overflow-x-auto">
          <TabsList variant="line" aria-label="Artifacts">
            {PANEL_TABS.map(({ id, label, icon: Icon }) => (
              // Seven labels don't fit the panel: inactive tabs show only their icon (named for screen readers
              // and with a tooltip), the active tab also shows its label.
              <TabsTrigger key={id} value={id} aria-label={label} title={label} className="flex-none px-2">
                <Icon aria-hidden="true" />
                <span className="hidden in-data-active:inline">{label}</span>
              </TabsTrigger>
            ))}
          </TabsList>
        </div>
        <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="Close side panel">
          <X aria-hidden="true" />
        </Button>
      </div>
      {PANEL_TABS.map(({ id, label, icon: Icon, empty }) => (
        <TabsContent key={id} value={id} className="min-h-0 overflow-y-auto p-6">
          <div className="flex h-full flex-col items-center justify-center gap-3 text-center text-muted-foreground">
            <span className="flex size-10 items-center justify-center rounded-full bg-muted">
              <Icon className="size-4" aria-hidden="true" />
            </span>
            <p className="font-medium text-foreground">{label}</p>
            <p className="max-w-60 text-sm">{empty}</p>
          </div>
        </TabsContent>
      ))}
    </Tabs>
  );
}
