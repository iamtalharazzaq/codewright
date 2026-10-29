"use client";

import { ChevronDownIcon } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

/** A full-width dropdown with a tick-box per option: the trigger lists what is ticked, the list stays open while ticking. */
export function MultiSelect({
  id,
  values,
  options,
  onChange,
  disabled,
  placeholder = "None",
}: {
  id: string;
  values: string[];
  options: string[];
  onChange: (values: string[]) => void;
  disabled?: boolean;
  /** Shown while nothing is ticked. */
  placeholder?: string;
}) {
  const ticked = options.filter((o) => values.includes(o));
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        id={id}
        disabled={disabled}
        className={cn(
          "flex h-9 w-full items-center justify-between gap-2 rounded-lg border border-input bg-transparent py-2 pr-2 pl-2.5 text-left text-sm outline-none",
          "focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-input/30",
        )}
      >
        <span className={cn("line-clamp-1", ticked.length === 0 && "text-muted-foreground")}>
          {ticked.length > 0 ? ticked.join(", ") : placeholder}
        </span>
        <ChevronDownIcon className="size-4 shrink-0 text-muted-foreground" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="min-w-64">
        {options.map((o) => (
          <DropdownMenuCheckboxItem
            key={o}
            checked={ticked.includes(o)}
            closeOnClick={false}
            onCheckedChange={(on) => onChange(options.filter((x) => (x === o ? on : ticked.includes(x))))}
          >
            {o}
          </DropdownMenuCheckboxItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
