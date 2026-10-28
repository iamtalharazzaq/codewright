"use client";

import "@xterm/xterm/css/xterm.css";

import { useEffect, useRef, useState } from "react";

import { previewOutputUrl, resizePreview, sendPreviewInput, type Preview } from "@/lib/api";

const LIGHT = { background: "#ffffff", foreground: "#1f2328", cursor: "#1f2328", selectionBackground: "#0969da33" };
const DARK = { background: "#0d1117", foreground: "#e6edf3", cursor: "#e6edf3", selectionBackground: "#388bfd55" };

function decode(b64: string): Uint8Array {
  const raw = atob(b64);
  const bytes = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
  return bytes;
}

/**
 * The interactive terminal preview (CODEWRIGHT.md Phase 5): a CLI or console app running in the sandbox with a real
 * TTY. Output arrives over SSE (scrollback first, then live); keystrokes are sent in small batches.
 */
export function TerminalView({ projectId, preview }: { projectId: string; preview: Preview }) {
  const host = useRef<HTMLDivElement>(null);
  const [exited, setExited] = useState<number | null>(preview.running ? null : (preview.exit_code ?? -1));

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    let disposed = false;
    let cleanup = () => {};
    void (async () => {
      // xterm touches `window` on import, so it loads only in the browser.
      const [{ Terminal }, { FitAddon }] = await Promise.all([import("@xterm/xterm"), import("@xterm/addon-fit")]);
      if (disposed) return;
      const dark = document.documentElement.classList.contains("dark");
      const term = new Terminal({
        convertEol: false,
        cursorBlink: true,
        fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
        fontSize: 13,
        scrollback: 5000,
        theme: dark ? DARK : LIGHT,
      });
      const fit = new FitAddon();
      term.loadAddon(fit);
      term.open(el);
      fit.fit();

      let pending = "";
      let timer: ReturnType<typeof setTimeout> | null = null;
      const flush = () => {
        timer = null;
        const data = pending;
        pending = "";
        if (data) void sendPreviewInput(projectId, preview.id, data).catch(() => undefined);
      };
      const input = term.onData((data) => {
        pending += data;
        timer ??= setTimeout(flush, 15);
      });

      let lastSize = "";
      const sendSize = () => {
        fit.fit();
        const size = `${term.rows}x${term.cols}`;
        if (size === lastSize) return;
        lastSize = size;
        void resizePreview(projectId, preview.id, term.rows, term.cols).catch(() => undefined);
      };
      const observer = new ResizeObserver(() => sendSize());
      observer.observe(el);
      sendSize();

      const source = new EventSource(previewOutputUrl(projectId, preview.id));
      source.addEventListener("output", (e) => {
        term.write(decode((JSON.parse((e as MessageEvent<string>).data) as { b64: string }).b64));
      });
      source.addEventListener("exit", (e) => {
        const info = JSON.parse((e as MessageEvent<string>).data) as Preview;
        setExited(info.exit_code ?? -1);
        source.close();
      });
      term.focus();

      cleanup = () => {
        source.close();
        observer.disconnect();
        input.dispose();
        if (timer) clearTimeout(timer);
        term.dispose();
      };
    })();
    return () => {
      disposed = true;
      cleanup();
    };
  }, [projectId, preview.id]);

  return (
    <div className="flex h-full min-h-64 flex-col gap-2">
      <div
        ref={host}
        className="min-h-0 flex-1 overflow-hidden rounded-lg border bg-white p-2 dark:bg-[#0d1117]"
        role="application"
        aria-label={`Terminal: ${preview.name}`}
      />
      {exited !== null && (
        <p role="status" className="text-xs text-muted-foreground">
          The program ended (exit code {exited}). Run it again to restart.
        </p>
      )}
    </div>
  );
}
