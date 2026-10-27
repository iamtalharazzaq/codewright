"use client";

import { Check, Copy } from "lucide-react";
import { useTheme } from "next-themes";
import { isValidElement, useEffect, useId, useState, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";

import { Button } from "@/components/ui/button";

/** Assistant replies: GitHub Markdown, highlighted code with a copy button, and Mermaid diagrams. */
export function Markdown({ children }: { children: string }) {
  return (
    <div className="prose-chat">
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]} components={COMPONENTS}>
        {children}
      </ReactMarkdown>
    </div>
  );
}

function textOf(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (isValidElement<{ children?: ReactNode }>(node)) return textOf(node.props.children);
  return "";
}

const COMPONENTS: Components = {
  pre({ children }) {
    const code = isValidElement<{ className?: string; children?: ReactNode }>(children) ? children : null;
    const language = /language-([\w+#-]+)/.exec(code?.props.className ?? "")?.[1];
    const text = textOf(code?.props.children ?? children).replace(/\n$/, "");
    if (language === "mermaid") return <Mermaid source={text} />;
    return (
      <div className="group/code relative my-3 overflow-hidden rounded-lg border bg-muted/40">
        <div className="flex items-center justify-between border-b px-3 py-1 text-xs text-muted-foreground">
          <span>{language ?? "text"}</span>
          <CopyButton text={text} />
        </div>
        <pre className="overflow-x-auto p-3 text-[13px] leading-relaxed">{children}</pre>
      </div>
    );
  },
  a({ href, children }) {
    return (
      <a href={href} target="_blank" rel="noreferrer noopener" className="text-primary underline underline-offset-2">
        {children}
      </a>
    );
  },
};

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      variant="ghost"
      size="icon-xs"
      aria-label={copied ? "Copied" : label}
      title={copied ? "Copied" : label}
      onClick={() => {
        void navigator.clipboard.writeText(text).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        });
      }}
    >
      {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
    </Button>
  );
}

/** Renders a ```mermaid block; shows the source if it doesn't parse (small models get syntax wrong sometimes). */
function Mermaid({ source }: { source: string }) {
  const id = useId().replace(/[^a-zA-Z0-9]/g, "");
  const { resolvedTheme } = useTheme();
  const [svg, setSvg] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void import("mermaid")
      .then(async ({ default: mermaid }) => {
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: "strict",
          theme: resolvedTheme === "dark" ? "dark" : "default",
        });
        const { svg: out } = await mermaid.render(`m${id}`, source);
        if (!cancelled) setSvg(out);
      })
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
    };
  }, [id, source, resolvedTheme]);

  if (failed || svg === null) {
    return (
      <pre className="my-3 overflow-x-auto rounded-lg border bg-muted/40 p-3 text-[13px]">
        {failed ? source : "Rendering diagram…"}
      </pre>
    );
  }
  // Mermaid's strict security level sanitizes the SVG it produces.
  return <div className="my-3 flex justify-center overflow-x-auto" dangerouslySetInnerHTML={{ __html: svg }} />;
}
