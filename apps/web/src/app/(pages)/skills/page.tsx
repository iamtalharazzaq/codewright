import type { Metadata } from "next";

import { SkillsView } from "@/components/skills/skills-view";

export const metadata: Metadata = { title: "Skills" };

export default function SkillsPage() {
  return (
    <section aria-labelledby="skills-heading" className="flex flex-col gap-6">
      <header className="flex flex-col gap-1">
        <h1 id="skills-heading" className="font-heading text-2xl font-semibold tracking-tight">
          Skills
        </h1>
        <p className="text-sm text-muted-foreground">
          Named procedures you run with a slash command, or that Codewright picks for you when a request matches. Skills
          add steps and rules; they never skip a confirmation, an approval or the sandbox.
        </p>
      </header>
      <SkillsView />
    </section>
  );
}
