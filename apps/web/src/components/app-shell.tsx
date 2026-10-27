import { FolderGit2, Settings, Waypoints, Workflow } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { ThemeToggle } from "@/components/theme-toggle";

interface NavItem {
  label: string;
  href: string;
  icon: typeof FolderGit2;
  // Screens that arrive in later roadmap phases are listed but not yet clickable.
  availableIn?: string;
}

const NAV: NavItem[] = [
  { label: "Projects", href: "/", icon: FolderGit2 },
  { label: "Runs", href: "/runs", icon: Workflow },
  { label: "Settings", href: "/settings", icon: Settings },
];

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col md:flex-row">
      <a
        href="#main"
        className="sr-only z-50 rounded-md bg-background px-3 py-2 focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
      >
        Skip to content
      </a>
      <aside className="flex shrink-0 items-center justify-between gap-4 border-b bg-sidebar px-4 py-3 text-sidebar-foreground md:w-60 md:flex-col md:items-stretch md:justify-start md:border-r md:border-b-0 md:py-5">
        <Link href="/" className="flex items-center gap-2 rounded-md font-heading text-base font-semibold">
          <span className="flex size-8 items-center justify-center rounded-lg bg-brand text-brand-foreground">
            <Waypoints className="size-4" aria-hidden="true" />
          </span>
          MonoShift
        </Link>
        <nav aria-label="Main" className="flex gap-1 md:mt-6 md:flex-col">
          {NAV.map(({ label, href, icon: Icon, availableIn }) =>
            availableIn ? (
              <span
                key={href}
                aria-disabled="true"
                title={`Available in ${availableIn}`}
                className="flex items-center gap-2 rounded-md px-3 py-2 text-sm text-muted-foreground"
              >
                <Icon className="size-4" aria-hidden="true" />
                <span className="hidden sm:inline">{label}</span>
              </span>
            ) : (
              <Link
                key={href}
                href={href}
                className="flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
              >
                <Icon className="size-4" aria-hidden="true" />
                <span className="hidden sm:inline">{label}</span>
              </Link>
            ),
          )}
        </nav>
        <div className="md:mt-auto">
          <ThemeToggle />
        </div>
      </aside>
      <main id="main" className="flex-1 px-4 py-6 sm:px-8 sm:py-10">
        <div className="mx-auto w-full max-w-5xl">{children}</div>
      </main>
    </div>
  );
}
