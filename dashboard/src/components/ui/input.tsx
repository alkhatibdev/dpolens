import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

export function Input({ className, type = "text", ...props }: ComponentProps<"input">) {
  return (
    <input
      type={type}
      className={cn(
        "h-13 w-full min-w-0 rounded-[14px] border-[1.5px] border-line-strong bg-white px-4 text-base text-ink placeholder:text-muted focus-visible:border-brand focus-visible:outline-none aria-invalid:border-danger-ink",
        className,
      )}
      {...props}
    />
  );
}
