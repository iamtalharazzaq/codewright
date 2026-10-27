import type { Metadata } from "next";
import { Suspense } from "react";

import { ProjectHome } from "@/components/projects/project-home";

export const metadata: Metadata = { title: "Project" };

// Cache Components: read the dynamic param inside <Suspense> so the shell can still prerender.
export default function ProjectPage({ params }: PageProps<"/projects/[id]">) {
  return (
    <Suspense fallback={<p className="text-sm text-muted-foreground">Loading project…</p>}>
      <Project params={params} />
    </Suspense>
  );
}

async function Project({ params }: Pick<PageProps<"/projects/[id]">, "params">) {
  const { id } = await params;
  return <ProjectHome key={id} projectId={id} />;
}
