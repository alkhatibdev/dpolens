import { Lock, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/** A box in a dialog or under a form: a refusal, a warning, or a quiet note. */
export function Notice({
  tone,
  children,
  className,
}: {
  tone: "danger" | "warn" | "quiet";
  children: ReactNode;
  className?: string;
}) {
  const look = {
    danger: "bg-danger-soft text-danger-ink",
    warn: "bg-warn-soft text-warn-ink",
    quiet: "bg-panel text-ink-2",
  }[tone];
  const Icon = tone === "quiet" ? Lock : TriangleAlert;
  return (
    <div
      role={tone === "danger" ? "alert" : undefined}
      className={cn(
        "flex items-start gap-2.5 rounded-[14px] px-4 py-3 text-sm leading-relaxed",
        look,
        className,
      )}
    >
      <Icon aria-hidden className="mt-0.5 size-[18px] shrink-0" />
      <div>{children}</div>
    </div>
  );
}
