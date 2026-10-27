import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const TONES = {
  ok: "border-success/30 bg-success/10 text-success",
  warn: "border-warning/30 bg-warning/10 text-warning",
  bad: "border-destructive/30 bg-destructive/10 text-destructive",
  info: "border-brand/30 bg-brand/10 text-brand",
  muted: "",
} as const;

const STATUS_TONE: Record<string, keyof typeof TONES> = {
  ok: "ok",
  completed: "ok",
  approve: "ok",
  running: "info",
  created: "info",
  waiting: "warn",
  loading: "warn",
  edit: "warn",
  not_configured: "muted",
  cancelled: "muted",
  unreachable: "bad",
  error: "bad",
  failed: "bad",
  reject: "bad",
};

export function StatusBadge({ status, label }: { status: string; label?: string }) {
  const tone = STATUS_TONE[status] ?? "muted";
  return (
    <Badge variant="outline" className={cn("capitalize", TONES[tone])}>
      {label ?? status.replaceAll("_", " ")}
    </Badge>
  );
}
