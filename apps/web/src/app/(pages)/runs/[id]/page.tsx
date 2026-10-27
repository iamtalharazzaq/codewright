import type { Metadata } from "next";
import { Suspense } from "react";

import { RunView } from "@/components/runs/run-view";

export const metadata: Metadata = { title: "Run" };

// Cache Components: read the dynamic param inside <Suspense> so the shell can still prerender.
export default function RunPage({ params }: PageProps<"/runs/[id]">) {
  return (
    <Suspense fallback={<p className="text-sm text-muted-foreground">Loading run…</p>}>
      <Run params={params} />
    </Suspense>
  );
}

async function Run({ params }: Pick<PageProps<"/runs/[id]">, "params">) {
  const { id } = await params;
  return <RunView runId={id} />;
}
