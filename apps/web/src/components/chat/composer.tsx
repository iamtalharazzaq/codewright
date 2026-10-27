"use client";

import { ArrowUp, Paperclip } from "lucide-react";
import { useId, type FormEvent, type KeyboardEvent } from "react";

import { Button } from "@/components/ui/button";

/**
 * The message box. Enter sends, Shift+Enter adds a line. `disabledReason` keeps the box usable for typing while
 * sending is not available yet (replies arrive in Phase 2).
 */
export function Composer({
  value,
  onChange,
  onSend,
  disabledReason,
}: {
  value: string;
  onChange: (value: string) => void;
  onSend: (text: string) => void;
  disabledReason?: string;
}) {
  const hintId = useId();
  const canSend = value.trim().length > 0 && !disabledReason;

  function submit(e?: FormEvent) {
    e?.preventDefault();
    if (canSend) onSend(value.trim());
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) submit(e);
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-1.5">
      <div className="rounded-2xl border bg-card shadow-sm transition-shadow focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/30">
        <label htmlFor={`${hintId}-input`} className="sr-only">
          Message Codewright
        </label>
        <textarea
          id={`${hintId}-input`}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={onKeyDown}
          rows={2}
          placeholder="Ask Codewright to explain, fix or build…"
          aria-describedby={disabledReason ? hintId : undefined}
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
          <Button type="submit" size="icon-sm" disabled={!canSend} aria-label="Send message" className="rounded-full">
            <ArrowUp aria-hidden="true" />
          </Button>
        </div>
      </div>
      {disabledReason && (
        <p id={hintId} className="px-2 text-center text-xs text-muted-foreground">
          {disabledReason}
        </p>
      )}
    </form>
  );
}
