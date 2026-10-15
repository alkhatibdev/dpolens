import { cva, type VariantProps } from "class-variance-authority";
import { Slot } from "radix-ui";
import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-2 font-semibold whitespace-nowrap transition-colors disabled:pointer-events-none disabled:opacity-60 [&_svg]:pointer-events-none [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        primary: "bg-brand text-white hover:bg-brand-dark",
        dark: "bg-ink text-white hover:bg-ink-2",
        outline: "border-[1.5px] border-brand-dark text-brand-dark hover:bg-brand-soft",
        quiet: "bg-field text-ink hover:bg-line",
        ghost: "text-ink-2 hover:bg-field",
        pill: "rounded-full border border-line-strong bg-white text-ink font-medium hover:bg-field",
        danger: "bg-danger-ink text-white hover:bg-danger-ink/90",
        "danger-outline": "border-[1.5px] border-danger-soft text-danger-ink hover:bg-danger-soft",
      },
      size: {
        md: "h-12 rounded-[14px] px-5 text-[15px]",
        sm: "h-11 rounded-xl px-4 text-sm",
        icon: "size-11 rounded-full",
      },
    },
    defaultVariants: { variant: "primary", size: "md" },
  },
);

type ButtonProps = ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & { asChild?: boolean };

export function Button({ className, variant, size, asChild = false, ...props }: ButtonProps) {
  const Component = asChild ? Slot.Root : "button";
  return <Component className={cn(buttonVariants({ variant, size }), className)} {...props} />;
}

export { buttonVariants };
