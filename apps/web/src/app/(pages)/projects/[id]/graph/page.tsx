import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { GraphView } from "@/components/graph/graph-view";

export const metadata: Metadata = { title: "Graph explorer" };

// Cache Components: read the dynamic param inside <Suspense> so the shell can still prerender.
export default function GraphPage({ params }: PageProps<"/projects/[id]/graph">) {
  return (
    <Suspense fallback={<p className="text-sm text-muted-foreground">Loading graph…</p>}>
      <Explorer params={params} />
    </Suspense>
  );
}

async function Explorer({ params }: Pick<PageProps<"/projects/[id]/graph">, "params">) {
  const { id } = await params;
  return (
    <section aria-labelledby="graph-heading" className="flex flex-col gap-4">
      <header className="flex items-baseline gap-3">
        <h1 id="graph-heading" className="font-heading text-2xl font-semibold tracking-tight">
          Graph explorer
        </h1>
        <Link href={`/projects/${id}`} className="text-sm text-muted-foreground hover:underline">
          Back to project
        </Link>
      </header>
      <GraphView key={id} projectId={id} />
    </section>
  );
}
