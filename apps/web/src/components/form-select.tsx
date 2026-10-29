"use client";

import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export interface SelectOption {
  value: string;
  label: string;
  /** A second, muted line under the label in the list. */
  hint?: string;
  /** Shown but not selectable, with a "Soon" badge. */
  disabled?: boolean;
}

/** A full-width dropdown for forms: the trigger shows the label, the list shows label, hint and a check. */
export function FormSelect({
  id,
  value,
  options,
  onChange,
  disabled,
  placeholder,
}: {
  id: string;
  value: string;
  options: SelectOption[];
  onChange: (value: string) => void;
  disabled?: boolean;
  /** Shown while no option is chosen. */
  placeholder?: string;
}) {
  const items = Object.fromEntries(options.map((o) => [o.value, o.label]));
  return (
    <Select
      value={value}
      items={items}
      disabled={disabled}
      onValueChange={(v) => {
        if (typeof v === "string") onChange(v);
      }}
    >
      <SelectTrigger id={id} className="h-9 w-full">
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent alignItemWithTrigger={false} align="start">
        {options.map((o) => (
          <SelectItem key={o.value} value={o.value} disabled={o.disabled} className="py-1.5">
            <span className="flex min-w-0 flex-col gap-0.5">
              <span className="flex items-center gap-2">
                {o.label}
                {o.disabled && <Badge variant="secondary">Soon</Badge>}
              </span>
              {o.hint && <span className="text-xs whitespace-normal text-muted-foreground">{o.hint}</span>}
            </span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
