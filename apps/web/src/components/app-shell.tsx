"use client";

import { FolderGit2, Menu, MessageSquarePlus, PenTool, Settings, Sparkles, Workflow, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Suspense, useState, type ReactNode } from "react";

import { ModelIndicator } from "@/components/shell/model-indicator";
import { SidebarChats } from "@/components/shell/sidebar-chats";
import { SidebarProjects } from "@/components/shell/sidebar-projects";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const NAV_LINK =
  "flex items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-sidebar-accent hover:text-sidebar-accent-foreground";

interface NavLinkProps {
  href: string;
  icon: typeof Settings;
  children: ReactNode;
  onNavigate: () => void;
}

// With Cache Components, `usePathname` suspends on routes with unknown dynamic params (e.g. /runs/[id]), so the
// active-state read sits in its own Suspense boundary; the fallback is the same link without highlighting.
function NavLink(props: NavLinkProps) {
  return (
    <Suspense fallback={<NavLinkView {...props} active={false} />}>
      <ActiveNavLink {...props} />
    </Suspense>
  );
}

function ActiveNavLink(props: NavLinkProps) {
  const pathname = usePathname();
  const active = props.href === "/" ? pathname === "/" : pathname.startsWith(props.href);
  return <NavLinkView {...props} active={active} />;
}

function NavLinkView({ href, icon: Icon, children, onNavigate, active }: NavLinkProps & { active: boolean }) {
  return (
    <Link
      href={href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={cn(NAV_LINK, active && "bg-sidebar-accent font-medium text-sidebar-accent-foreground")}
    >
      <Icon className="size-4 shrink-0" aria-hidden="true" />
      {children}
    </Link>
  );
}

function SectionHeading({ children }: { children: ReactNode }) {
  return <h2 className="px-2 pb-1 text-xs font-medium text-muted-foreground">{children}</h2>;
}

/**
 * Claude-style app frame (README Section 2.1): a sidebar with new chat, projects, chats, the model status and
 * settings; the page fills the rest. On small screens the sidebar is a drawer opened from the top bar.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const close = () => setDrawerOpen(false);

  return (
    <div className="flex h-dvh flex-col overflow-hidden md:flex-row">
      <a
        href="#main"
        className="sr-only z-50 rounded-md bg-background px-3 py-2 focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
      >
        Skip to content
      </a>

      {/* Top bar, small screens only. */}
      <div className="flex shrink-0 items-center gap-2 border-b bg-sidebar px-2 py-2 md:hidden">
        <Button
          variant="ghost"
          size="icon"
          onClick={() => setDrawerOpen(true)}
          aria-label="Open sidebar"
          aria-expanded={drawerOpen}
          aria-controls="sidebar"
        >
          <Menu aria-hidden="true" />
        </Button>
        <Brand />
      </div>

      {drawerOpen && (
        <button
          type="button"
          aria-label="Close sidebar"
          tabIndex={-1}
          onClick={close}
          className="fixed inset-0 z-30 bg-black/40 md:hidden"
        />
      )}

      <aside
        id="sidebar"
        className={cn(
          "z-40 w-72 shrink-0 flex-col border-r bg-sidebar text-sidebar-foreground md:static md:flex md:w-64",
          drawerOpen ? "fixed inset-y-0 left-0 flex shadow-xl" : "hidden",
        )}
      >
        <div className="flex items-center justify-between px-3 pt-4 pb-2">
          <Brand onNavigate={close} />
          <Button variant="ghost" size="icon" onClick={close} aria-label="Close sidebar" className="md:hidden">
            <X aria-hidden="true" />
          </Button>
        </div>

        <nav aria-label="Main" className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-2 pb-2">
          <div className="flex flex-col gap-0.5">
            <NavLink href="/" icon={MessageSquarePlus} onNavigate={close}>
              New chat
            </NavLink>
            <NavLink href="/skills" icon={Sparkles} onNavigate={close}>
              Skills
            </NavLink>
          </div>

          <section aria-labelledby="sidebar-projects" className="flex flex-col">
            <SectionHeading>
              <span id="sidebar-projects">Projects</span>
            </SectionHeading>
            <NavLink href="/projects" icon={FolderGit2} onNavigate={close}>
              All projects
            </NavLink>
            <SidebarProjects onNavigate={close} />
          </section>

          <section aria-labelledby="sidebar-chats" className="flex flex-col">
            <SectionHeading>
              <span id="sidebar-chats">Chats</span>
            </SectionHeading>
            <SidebarChats onNavigate={close} />
          </section>

          <section aria-labelledby="sidebar-dev" className="mt-auto flex flex-col">
            <SectionHeading>
              <span id="sidebar-dev">Runs</span>
            </SectionHeading>
            <NavLink href="/runs" icon={Workflow} onNavigate={close}>
              Run history
            </NavLink>
          </section>
        </nav>

        <div className="flex flex-col gap-1 border-t px-2 py-2">
          <ModelIndicator />
          <div className="flex items-center justify-between">
            <NavLink href="/settings" icon={Settings} onNavigate={close}>
              Settings
            </NavLink>
            <ThemeToggle />
          </div>
        </div>
      </aside>

      <main id="main" className="min-h-0 min-w-0 flex-1">
        {children}
      </main>
    </div>
  );
}

function Brand({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <Link
      href="/"
      onClick={onNavigate}
      className="flex items-center gap-2 rounded-md font-heading text-base font-semibold"
    >
      <span className="flex size-7 items-center justify-center rounded-lg bg-brand text-brand-foreground">
        <PenTool className="size-3.5" aria-hidden="true" />
      </span>
      Codewright
    </Link>
  );
}
