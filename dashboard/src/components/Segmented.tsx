import type { ReactNode } from "react";
import { NavLink } from "react-router";

import { cn } from "@/lib/utils";

const item = "inline-flex h-10 items-center rounded-full px-[18px] text-[15px] whitespace-nowrap";
const on = "bg-ink font-semibold text-white";
const off = "text-ink-2 hover:bg-field";

/** Sections of one page, as links: the current one dark, the rest quiet. */
export function SectionTabs({
  label,
  items,
}: {
  label: string;
  items: { to: string; label: ReactNode; end?: boolean }[];
}) {
  return (
    <nav
      aria-label={label}
      className="inline-flex flex-wrap gap-1 self-start rounded-full bg-white p-1"
    >
      {items.map(({ to, label: text, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          className={({ isActive }) => cn(item, isActive ? on : off)}
        >
          {text}
        </NavLink>
      ))}
    </nav>
  );
}

/** The same look for a choice that stays on the page, such as whose tokens to list. */
export function SegmentedChoice<T extends string>({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: T;
  onChange: (value: T) => void;
  options: { value: T; label: ReactNode }[];
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className="inline-flex flex-wrap gap-1 self-start rounded-full bg-white p-1"
    >
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={value === option.value}
          onClick={() => onChange(option.value)}
          className={cn(item, value === option.value ? on : off)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
