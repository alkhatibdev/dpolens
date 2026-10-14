import { Switch as SwitchPrimitive } from "radix-ui";
import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

export function Switch({ className, ...props }: ComponentProps<typeof SwitchPrimitive.Root>) {
  return (
    <SwitchPrimitive.Root
      className={cn(
        "inline-flex h-5 w-9 shrink-0 items-center rounded-full bg-line-strong transition-colors data-[state=checked]:bg-brand",
        className,
      )}
      {...props}
    >
      <SwitchPrimitive.Thumb className="block size-3.5 translate-x-[3px] rounded-full bg-white transition-transform data-[state=checked]:translate-x-[19px] rtl:-translate-x-[3px] rtl:data-[state=checked]:-translate-x-[19px]" />
    </SwitchPrimitive.Root>
  );
}
