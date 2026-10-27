"use client";

import { FolderGit2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { listProjects, type Project } from "@/lib/api";

/** Sidebar "Projects" list. Opening a project's home arrives in Phase 3; until then it links to the list. */
export function SidebarProjects({ onNavigate }: { onNavigate?: () => void }) {
  const [projects, setProjects] = useState<Project[] | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    listProjects(controller.signal)
      .then(setProjects)
      .catch(() => {
        if (!controller.signal.aborted) setProjects([]);
      });
    return () => controller.abort();
  }, []);

  if (projects === null) return <p className="px-2 text-xs text-muted-foreground">Loading…</p>;
  if (projects.length === 0) return <p className="px-2 text-xs text-muted-foreground">No projects yet</p>;
  return (
    <ul className="flex flex-col gap-0.5">
      {projects.slice(0, 8).map((p) => (
        <li key={p.id}>
          <Link
            href="/projects"
            onClick={onNavigate}
            className="flex items-center gap-2 truncate rounded-md px-2 py-1.5 text-sm hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
          >
            <FolderGit2 className="size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
            <span className="truncate">{p.name}</span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
