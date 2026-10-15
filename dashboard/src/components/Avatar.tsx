import { Bot } from "lucide-react";

import { initialsOf } from "@/lib/names";
import { cn } from "@/lib/utils";

/** A person's initials, or a robot for a service account, in a soft circle. */
export function Avatar({
  name,
  service = false,
  size = 32,
  className,
}: {
  name: string;
  service?: boolean;
  size?: 28 | 32 | 36;
  className?: string;
}) {
  const dimensions = { 28: "size-7 text-[11px]", 32: "size-8 text-xs", 36: "size-9 text-[13px]" }[
    size
  ];
  return (
    <span
      aria-hidden
      className={cn(
        "grid shrink-0 place-items-center rounded-full font-semibold",
        service ? "bg-field text-ink-2" : "bg-brand-soft text-brand-dark",
        dimensions,
        className,
      )}
    >
      {service ? <Bot className="size-1/2" /> : initialsOf(name)}
    </span>
  );
}
