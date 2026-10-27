import { Loader2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";

export function StatusBadge({ status }: { status: string }) {
  if (status === "importing") {
    return (
      <Badge variant="outline" className="gap-1">
        <Loader2 className="size-3 animate-spin" aria-hidden="true" />
        importing
      </Badge>
    );
  }
  return <Badge variant={status === "failed" ? "destructive" : "outline"}>{status}</Badge>;
}
