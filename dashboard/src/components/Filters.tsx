import { Search } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/** A pill that narrows a list, dark while it is on. */
export function FilterButton({
  pressed,
  onClick,
  children,
  lang,
}: {
  pressed: boolean;
  onClick: () => void;
  children: ReactNode;
  lang?: string;
}) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onClick}
      lang={lang}
      className={cn(
        "h-11 rounded-full px-4 text-sm font-medium whitespace-nowrap",
        pressed ? "bg-ink text-white" : "border border-line-strong bg-white hover:bg-field",
      )}
    >
      {children}
    </button>
  );
}

/** A search box that filters what is already on the page. */
export function FindBox({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="flex h-11 min-w-0 flex-[1_1_280px] items-center gap-2.5 rounded-full border border-line-strong bg-white px-4 sm:max-w-[420px]">
      <Search aria-hidden className="size-4 shrink-0 text-muted" />
      <span className="sr-only">{label}</span>
      <input
        type="search"
        value={value}
        placeholder={label}
        onChange={(event) => onChange(event.target.value)}
        className="min-w-0 flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-muted"
      />
    </label>
  );
}
