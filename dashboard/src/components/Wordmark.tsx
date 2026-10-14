import { cn } from "@/lib/utils";

/** The name alone, until there is a logo. */
export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={cn("text-[23px] font-semibold tracking-[-0.02em]", className)}>DPOLens</span>
  );
}
