import type { ReactNode } from "react";

/** A page's title, the line under it, and its one main action. */
export function PageHeading({
  title,
  subtitle,
  action,
}: {
  title: ReactNode;
  subtitle: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0 flex-[1_1_420px]">
        <h1 className="text-[32px] leading-tight font-semibold tracking-[-0.025em] sm:text-[40px]">
          {title}
        </h1>
        <p className="mt-1.5 max-w-[62ch] text-[15px] leading-relaxed text-muted sm:text-base">
          {subtitle}
        </p>
      </div>
      {action ? <div className="flex flex-wrap gap-2.5">{action}</div> : null}
    </div>
  );
}

/** A white card holding a table that scrolls sideways on a phone rather than the page. */
export function TableCard({ children, footer }: { children: ReactNode; footer?: ReactNode }) {
  return (
    <div className="min-w-0 rounded-[20px] bg-white px-2 pt-1.5 pb-2">
      {/* relative: a visually hidden header label is positioned absolutely, and without a
          positioned scroll box it escapes the box and widens the whole page on a phone. */}
      <div className="relative overflow-x-auto">{children}</div>
      {footer ? <div className="px-4 pt-3.5 pb-2 text-sm text-muted">{footer}</div> : null}
    </div>
  );
}

export const th =
  "border-b border-line px-4 py-3.5 text-start text-xs font-semibold tracking-[0.06em] whitespace-nowrap text-muted uppercase";
export const td = "border-b border-line px-4 py-3.5 align-middle text-[15px] leading-normal";
