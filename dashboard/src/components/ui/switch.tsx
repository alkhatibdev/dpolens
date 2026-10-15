import { Switch as SwitchPrimitive } from "radix-ui";
import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

const sizes = {
  md: {
    root: "h-5 w-9",
    thumb:
      "size-3.5 translate-x-[3px] data-[state=checked]:translate-x-[19px] rtl:-translate-x-[3px] rtl:data-[state=checked]:-translate-x-[19px]",
  },
  lg: {
    root: "h-7 w-[46px]",
    thumb:
      "size-6 translate-x-[2px] shadow-sm data-[state=checked]:translate-x-[20px] rtl:-translate-x-[2px] rtl:data-[state=checked]:-translate-x-[20px]",
  },
} as const;

export function Switch({
  className,
  size = "md",
  ...props
}: ComponentProps<typeof SwitchPrimitive.Root> & { size?: keyof typeof sizes }) {
  return (
    <SwitchPrimitive.Root
      className={cn(
        "inline-flex shrink-0 items-center rounded-full bg-line-strong transition-colors disabled:opacity-60 data-[state=checked]:bg-brand",
        sizes[size].root,
        className,
      )}
      {...props}
    >
      <SwitchPrimitive.Thumb
        className={cn("block rounded-full bg-white transition-transform", sizes[size].thumb)}
      />
    </SwitchPrimitive.Root>
  );
}
