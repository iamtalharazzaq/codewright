import type { Metadata } from "next";

import { ProjectsView } from "@/components/projects/projects-view";

export const metadata: Metadata = { title: "Projects" };

export default function ProjectsPage() {
  return (
    <section aria-labelledby="projects-heading" className="flex flex-col gap-6">
      <header className="flex flex-col gap-1">
        <h1 id="projects-heading" className="font-heading text-2xl font-semibold tracking-tight">
          Projects
        </h1>
        <p className="text-sm text-muted-foreground">Codebases Codewright works on.</p>
      </header>
      <ProjectsView />
    </section>
  );
}
