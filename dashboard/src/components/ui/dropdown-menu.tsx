import { Check } from "lucide-react";
import { DropdownMenu as Menu } from "radix-ui";
import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

export const DropdownMenu = Menu.Root;
export const DropdownMenuTrigger = Menu.Trigger;

export function DropdownMenuContent({
  className,
  sideOffset = 8,
  ...props
}: ComponentProps<typeof Menu.Content>) {
  return (
    <Menu.Portal>
      <Menu.Content
        sideOffset={sideOffset}
        className={cn(
          "z-50 min-w-60 rounded-[18px] border border-line bg-white p-2 shadow-[0_18px_40px_rgba(17,22,19,0.12)] data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95",
          className,
        )}
        {...props}
      />
    </Menu.Portal>
  );
}

export function DropdownMenuItem({ className, ...props }: ComponentProps<typeof Menu.Item>) {
  return (
    <Menu.Item
      className={cn(
        "flex min-h-11 cursor-pointer items-center gap-3 rounded-xl px-3 text-[15px] text-ink outline-none select-none data-[highlighted]:bg-field [&_svg]:size-[18px] [&_svg]:text-muted",
        className,
      )}
      {...props}
    />
  );
}

export function DropdownMenuLabel({ className, ...props }: ComponentProps<typeof Menu.Label>) {
  return <Menu.Label className={cn("px-3 py-2", className)} {...props} />;
}

export function DropdownMenuSeparator({
  className,
  ...props
}: ComponentProps<typeof Menu.Separator>) {
  return <Menu.Separator className={cn("my-1 h-px bg-line", className)} {...props} />;
}

export const DropdownMenuRadioGroup = Menu.RadioGroup;

export function DropdownMenuRadioItem({
  className,
  children,
  ...props
}: ComponentProps<typeof Menu.RadioItem>) {
  return (
    <Menu.RadioItem
      className={cn(
        "flex min-h-11 cursor-pointer items-center gap-3 rounded-xl ps-3 pe-9 text-[15px] text-ink outline-none select-none data-[highlighted]:bg-field data-[state=checked]:font-semibold relative",
        className,
      )}
      {...props}
    >
      {children}
      <Menu.ItemIndicator className="absolute end-3">
        <Check aria-hidden className="size-4 text-brand" />
      </Menu.ItemIndicator>
    </Menu.RadioItem>
  );
}
