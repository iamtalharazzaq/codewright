"use client";

import { MoreHorizontal, Pencil, Pin, PinOff, Search, Trash2 } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  CONVERSATIONS_CHANGED,
  deleteConversation,
  listConversations,
  notifyConversationsChanged,
  patchConversation,
  type Conversation,
} from "@/lib/api";
import { cn } from "@/lib/utils";

/** Sidebar "Chats": search, then pinned and recent chats, each with rename / pin / delete. */
export function SidebarChats({ onNavigate }: { onNavigate?: () => void }) {
  const [query, setQuery] = useState("");
  const [chats, setChats] = useState<Conversation[] | null>(null);

  const load = useCallback(() => {
    listConversations(query.trim() || undefined)
      .then(setChats)
      .catch(() => setChats([]));
  }, [query]);

  useEffect(() => {
    const timer = setTimeout(load, 200); // debounce typing in the search box
    window.addEventListener(CONVERSATIONS_CHANGED, load);
    return () => {
      clearTimeout(timer);
      window.removeEventListener(CONVERSATIONS_CHANGED, load);
    };
  }, [load]);

  return (
    <div className="flex flex-col gap-1">
      <label className="relative mx-1 flex items-center">
        <span className="sr-only">Search chats</span>
        <Search className="pointer-events-none absolute left-2 size-3.5 text-muted-foreground" aria-hidden="true" />
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search chats"
          className="h-7 w-full rounded-md border border-sidebar-border bg-transparent pr-2 pl-7 text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
        />
      </label>
      {chats === null && <p className="px-2 text-xs text-muted-foreground">Loading…</p>}
      {chats?.length === 0 && (
        <p className="px-2 text-xs text-muted-foreground">{query ? "No matches" : "Your chats appear here."}</p>
      )}
      <ul className="flex flex-col gap-0.5">
        {chats?.map((c) => (
          <li key={c.id}>
            <Suspense fallback={<ChatItem chat={c} active={false} onNavigate={onNavigate} />}>
              <ActiveChatItem chat={c} onNavigate={onNavigate} />
            </Suspense>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ActiveChatItem({ chat, onNavigate }: { chat: Conversation; onNavigate?: () => void }) {
  const pathname = usePathname();
  return <ChatItem chat={chat} active={pathname === `/c/${chat.id}`} onNavigate={onNavigate} />;
}

function ChatItem({ chat, active, onNavigate }: { chat: Conversation; active: boolean; onNavigate?: () => void }) {
  const router = useRouter();
  const [renaming, setRenaming] = useState(false);
  const [title, setTitle] = useState(chat.title);

  async function rename() {
    setRenaming(false);
    const next = title.trim();
    if (next && next !== chat.title) {
      await patchConversation(chat.id, { title: next });
      notifyConversationsChanged();
    }
  }

  if (renaming) {
    return (
      <input
        autoFocus
        aria-label="Chat name"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        onBlur={() => void rename()}
        onKeyDown={(e) => {
          if (e.key === "Enter") void rename();
          if (e.key === "Escape") setRenaming(false);
        }}
        className="h-8 w-full rounded-md border bg-background px-2 text-sm outline-none"
      />
    );
  }

  return (
    <div
      className={cn(
        "group flex items-center rounded-md hover:bg-sidebar-accent",
        active && "bg-sidebar-accent font-medium text-sidebar-accent-foreground",
      )}
    >
      <Link
        href={`/c/${chat.id}`}
        onClick={onNavigate}
        aria-current={active ? "page" : undefined}
        className="flex min-w-0 flex-1 items-center gap-1.5 px-2 py-1.5 text-sm"
      >
        {chat.pinned && <Pin className="size-3 shrink-0 text-muted-foreground" aria-label="Pinned" />}
        <span className="truncate">{chat.title}</span>
      </Link>
      <DropdownMenu>
        <DropdownMenuTrigger
          aria-label={`Options for ${chat.title}`}
          className="mr-1 rounded p-1 text-muted-foreground opacity-0 group-hover:opacity-100 hover:text-foreground focus-visible:opacity-100 data-popup-open:opacity-100"
        >
          <MoreHorizontal className="size-4" aria-hidden="true" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem
            onClick={() => {
              setTitle(chat.title);
              setRenaming(true);
            }}
          >
            <Pencil aria-hidden="true" /> Rename
          </DropdownMenuItem>
          <DropdownMenuItem
            onClick={() => void patchConversation(chat.id, { pinned: !chat.pinned }).then(notifyConversationsChanged)}
          >
            {chat.pinned ? <PinOff aria-hidden="true" /> : <Pin aria-hidden="true" />}
            {chat.pinned ? "Unpin" : "Pin"}
          </DropdownMenuItem>
          <DropdownMenuItem
            variant="destructive"
            onClick={() => {
              if (!window.confirm(`Delete "${chat.title}"? This can't be undone.`)) return;
              void deleteConversation(chat.id).then(() => {
                notifyConversationsChanged();
                if (active) router.push("/");
              });
            }}
          >
            <Trash2 aria-hidden="true" /> Delete
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}
