"use client";

import { ArrowUp, Paperclip, Square } from "lucide-react";
import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

import { Button } from "@/components/ui/button";
import { listCommands, type SlashCommand } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * The message box. Enter sends, Shift+Enter adds a line. Typing `/` opens the command menu (Tab or click picks one).
 * While a reply is being written the send button becomes Stop.
 */
export function Composer({
  value,
  onChange,
  onSend,
  busy = false,
  onStop,
}: {
  value: string;
  onChange: (value: string) => void;
  onSend: (text: string) => void;
  busy?: boolean;
  onStop?: () => void;
}) {
  const id = useId();
  const input = useRef<HTMLTextAreaElement>(null);
  const [commands, setCommands] = useState<SlashCommand[]>([]);
  const [active, setActive] = useState(0);
  const canSend = value.trim().length > 0 && !busy;

  useEffect(() => {
    listCommands()
      .then(setCommands)
      .catch(() => setCommands([]));
  }, []);

  // The menu shows while the first word is being typed: "/rev" → /review-code.
  const typing = /^\/[\w-]*$/.test(value);
  const matches = typing ? commands.filter((c) => c.command.startsWith(value.toLowerCase())) : [];

  function pick(command: SlashCommand) {
    onChange(`${command.command} `);
    setActive(0);
    input.current?.focus();
  }

  function submit(e?: FormEvent) {
    e?.preventDefault();
    if (canSend) onSend(value.trim());
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (matches.length > 0) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        setActive((i) => (i + (e.key === "ArrowDown" ? 1 : matches.length - 1)) % matches.length);
        return;
      }
      if (e.key === "Tab" || (e.key === "Enter" && !e.shiftKey)) {
        e.preventDefault();
        pick(matches[Math.min(active, matches.length - 1)]);
        return;
      }
    }
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) submit(e);
  }

  return (
    <form onSubmit={submit} className="relative flex flex-col gap-1.5">
      {matches.length > 0 && (
        <ul
          id={`${id}-commands`}
          role="listbox"
          aria-label="Commands"
          className="absolute right-0 bottom-full left-0 mb-2 max-h-72 overflow-y-auto rounded-xl border bg-popover p-1 shadow-md"
        >
          {matches.map((c, i) => (
            <li
              key={c.command}
              role="option"
              aria-selected={i === active}
              onMouseDown={(e) => {
                e.preventDefault();
                pick(c);
              }}
              className={cn(
                "flex cursor-pointer items-baseline gap-3 rounded-lg px-3 py-1.5 text-sm",
                i === active && "bg-accent",
              )}
            >
              <span className="font-mono">{c.command}</span>
              <span className="truncate text-xs text-muted-foreground">{c.description}</span>
            </li>
          ))}
        </ul>
      )}
      <div className="rounded-2xl border bg-card shadow-sm transition-shadow focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/30">
        <label htmlFor={`${id}-input`} className="sr-only">
          Message Codewright
        </label>
        <textarea
          ref={input}
          id={`${id}-input`}
          value={value}
          onChange={(e) => {
            onChange(e.target.value);
            setActive(0);
          }}
          onKeyDown={onKeyDown}
          rows={2}
          placeholder="Ask Codewright to explain, fix or build… (type / for commands)"
          aria-controls={matches.length > 0 ? `${id}-commands` : undefined}
          className="block field-sizing-content max-h-60 min-h-14 w-full resize-none bg-transparent px-4 pt-3 text-base outline-none placeholder:text-muted-foreground md:text-sm"
        />
        <div className="flex items-center justify-between px-2 pb-2">
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            disabled
            title="Uploads arrive in Phase 3"
            aria-label="Attach files"
          >
            <Paperclip aria-hidden="true" />
          </Button>
          {busy && onStop ? (
            <Button type="button" size="icon-sm" onClick={onStop} aria-label="Stop" className="rounded-full">
              <Square className="fill-current" aria-hidden="true" />
            </Button>
          ) : (
            <Button type="submit" size="icon-sm" disabled={!canSend} aria-label="Send message" className="rounded-full">
              <ArrowUp aria-hidden="true" />
            </Button>
          )}
        </div>
      </div>
    </form>
  );
}
