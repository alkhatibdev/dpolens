import { Dialog as DialogPrimitive } from "radix-ui";
import type { ComponentProps, ReactNode } from "react";

import { cn } from "@/lib/utils";

export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogClose = DialogPrimitive.Close;

/** A dialog in the dashboard's look: a white card over the dimmed page. */
export function DialogContent({
  title,
  description,
  className,
  children,
  ...props
}: ComponentProps<typeof DialogPrimitive.Content> & { title: ReactNode; description?: ReactNode }) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-ink/50 data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=closed]:animate-out data-[state=closed]:fade-out-0" />
      <DialogPrimitive.Content
        // Without a description, say so, rather than leave Radix to look for one.
        {...(description ? {} : { "aria-describedby": undefined })}
        className={cn(
          "fixed start-1/2 top-1/2 z-50 flex max-h-[calc(100dvh-24px)] w-[min(560px,calc(100vw-24px))] -translate-x-1/2 -translate-y-1/2 flex-col gap-5 overflow-y-auto rounded-[24px] bg-white p-6 shadow-[0_24px_60px_rgba(17,22,19,0.28)] sm:p-7 rtl:translate-x-1/2 data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95",
          className,
        )}
        {...props}
      >
        <DialogPrimitive.Title className="text-[24px] leading-tight font-semibold tracking-[-0.015em]">
          {title}
        </DialogPrimitive.Title>
        {description ? (
          <DialogPrimitive.Description className="-mt-2 text-[15px] leading-relaxed text-ink-2">
            {description}
          </DialogPrimitive.Description>
        ) : null}
        {children}
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}

export function DialogActions({ children }: { children: ReactNode }) {
  return <div className="flex flex-wrap items-center gap-2.5">{children}</div>;
}
