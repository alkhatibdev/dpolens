import type { ReactNode } from "react";

import { Checkbox } from "@/components/ui/checkbox";
import { cn } from "@/lib/utils";

/** A checkbox as a card: its name, a line on what it means, and a note on the far side. */
export function ChoiceCard({
  id,
  checked,
  onChange,
  title,
  description,
  aside,
  disabled = false,
}: {
  id: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  aside?: ReactNode;
  disabled?: boolean;
}) {
  return (
    <label
      htmlFor={id}
      className={cn(
        "flex cursor-pointer items-start gap-3 rounded-2xl px-4 py-3.5",
        checked ? "border-2 border-brand bg-brand-soft" : "border border-line-strong bg-white",
        disabled && "cursor-not-allowed opacity-60",
      )}
    >
      <Checkbox
        id={id}
        checked={checked}
        disabled={disabled}
        onCheckedChange={(value) => onChange(value === true)}
        className="mt-0.5"
      />
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap justify-between gap-x-3 gap-y-0.5">
          <span className="text-[15px] font-semibold">{title}</span>
          {aside ? <span className="text-[13px] text-muted">{aside}</span> : null}
        </span>
        {description ? (
          <span className="mt-0.5 block text-[13px] leading-relaxed text-ink-2">{description}</span>
        ) : null}
      </span>
    </label>
  );
}
