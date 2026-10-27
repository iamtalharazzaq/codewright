import type { Metadata } from "next";

import { RunsView } from "@/components/runs/runs-view";

export const metadata: Metadata = { title: "Runs" };

export default function RunsPage() {
  return (
    <section aria-labelledby="runs-heading" className="flex flex-col gap-6">
      <header className="flex flex-col gap-1">
        <h1 id="runs-heading" className="font-heading text-2xl font-semibold tracking-tight">
          Runs
        </h1>
        <p className="text-sm text-muted-foreground">Each run walks the workflow and stops at every approval gate.</p>
      </header>
      <RunsView />
    </section>
  );
}
