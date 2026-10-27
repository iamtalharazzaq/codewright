"use client";

import { ArrowUp, FileText, Loader2, Paperclip, ShieldAlert, Square, X } from "lucide-react";
import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

import { Button } from "@/components/ui/button";
import { listCommands, uploadFile, type SlashCommand, type UploadInfo } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * The message box. Enter sends, Shift+Enter adds a line. Typing `/` opens the command menu (Tab or click picks one).
 * While a reply is being written the send button becomes Stop. The clip uploads files (secret-scanned on the server);
 * they go with the next message.
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
  onSend: (text: string, attachments: string[]) => void;
  busy?: boolean;
  onStop?: () => void;
}) {
  const id = useId();
  const input = useRef<HTMLTextAreaElement>(null);
  const [commands, setCommands] = useState<SlashCommand[]>([]);
  const [active, setActive] = useState(0);
  const [files, setFiles] = useState<UploadInfo[]>([]);
  const [uploading, setUploading] = useState(0);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const picker = useRef<HTMLInputElement>(null);
  const canSend = value.trim().length > 0 && !busy && uploading === 0;

  async function attach(list: FileList | null) {
    setUploadError(null);
    for (const file of Array.from(list ?? [])) {
      setUploading((n) => n + 1);
      try {
        const info = await uploadFile(file);
        setFiles((f) => [...f, info]);
      } catch (e) {
        setUploadError(`${file.name}: ${e instanceof Error ? e.message : String(e)}`);
      } finally {
        setUploading((n) => n - 1);
      }
    }
  }

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
    if (!canSend) return;
    onSend(
      value.trim(),
      files.map((f) => f.id),
    );
    setFiles([]);
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
      {uploadError && (
        <p role="alert" className="text-sm text-destructive">
          {uploadError}
        </p>
      )}
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
        {(files.length > 0 || uploading > 0) && (
          <ul aria-label="Attached files" className="flex flex-wrap gap-1.5 px-3 pt-3">
            {files.map((f) => (
              <li key={f.id} className="flex items-center gap-1 rounded-md border bg-muted px-2 py-1 text-xs">
                <FileText className="size-3.5" aria-hidden="true" />
                <span className="max-w-40 truncate">{f.filename}</span>
                {f.secrets.length > 0 && (
                  <span
                    className="flex items-center gap-0.5 text-amber-600 dark:text-amber-400"
                    title="Secrets are masked"
                  >
                    <ShieldAlert className="size-3.5" aria-hidden="true" />
                    {f.secrets.length} secret{f.secrets.length > 1 ? "s" : ""} masked
                  </span>
                )}
                <button
                  type="button"
                  aria-label={`Remove ${f.filename}`}
                  onClick={() => setFiles((all) => all.filter((x) => x.id !== f.id))}
                  className="rounded hover:bg-background"
                >
                  <X className="size-3.5" aria-hidden="true" />
                </button>
              </li>
            ))}
            {uploading > 0 && (
              <li className="flex items-center gap-1 px-2 py-1 text-xs text-muted-foreground">
                <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
                Uploading…
              </li>
            )}
          </ul>
        )}
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
          <input
            ref={picker}
            type="file"
            multiple
            hidden
            onChange={(e) => {
              void attach(e.target.files);
              e.target.value = "";
            }}
          />
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            onClick={() => picker.current?.click()}
            title="Attach files"
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
