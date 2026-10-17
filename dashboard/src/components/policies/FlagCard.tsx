import { Check, Flag } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { DraftFlag } from "@/api/policies";
import { isSettled, shortKey } from "@/lib/policies";
import { cn } from "@/lib/utils";

import { useSettledLine } from "./settled";

/** A flag's kind as a small warning chip, or a quiet one once it is settled. */
export function FlagChip({
  children,
  settled = false,
}: {
  children: ReactNode;
  settled?: boolean;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold whitespace-nowrap",
        settled ? "bg-field text-ink-2" : "bg-warn-soft text-warn-ink",
      )}
    >
      <Flag aria-hidden className="size-3" />
      {children}
    </span>
  );
}

/** One thing for a reviewer to settle: what the parser said, what to check, and what can be done. */
export function FlagCard({
  flag,
  slug,
  actions,
  compact = false,
  children,
  afterwards,
}: {
  flag: DraftFlag;
  slug: string;
  actions?: ReactNode;
  /** Inside a changed clause's row, which already names the clause. */
  compact?: boolean;
  /** What helps to settle it, shown until it is settled. */
  children?: ReactNode;
  /** What can still be done once it is settled, such as taking the decision back. */
  afterwards?: ReactNode;
}) {
  const { t } = useTranslation();
  const settledLine = useSettledLine(slug);
  const settled = isSettled(flag);
  return (
    <div
      className={cn(
        "flex flex-col gap-2.5 rounded-2xl border px-4 py-3.5",
        settled ? "border-line bg-white" : "border-warn-soft bg-white",
        compact && !settled && "border-[#f6d9b3] bg-[#fffbf5]",
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[13px] font-semibold text-muted tabular-nums">{flag.position}</span>
        <FlagChip settled={settled}>{t(`review.kinds.${flag.kind}`)}</FlagChip>
        {compact ? null : (
          <span className="font-mono text-[13px] font-medium text-brand-dark">
            {flag.key ? shortKey(flag.key, slug) : t("review.wholeFile")}
          </span>
        )}
        {settled ? (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-field px-2.5 py-1 text-xs font-semibold text-ink-2">
            <Check aria-hidden className="size-3" />
            {settledLine(flag)}
          </span>
        ) : null}
      </div>
      <p className={cn("text-sm leading-relaxed", settled ? "text-ink-2" : "text-ink")}>
        {flag.detail}
        {settled || compact ? null : (
          <span className="mt-1 block text-[13px] text-muted">
            {t(`review.kindHelp.${flag.kind}`)}
          </span>
        )}
      </p>
      {!settled && children ? children : null}
      {!settled && actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
      {settled && afterwards ? <div className="flex flex-wrap gap-2">{afterwards}</div> : null}
    </div>
  );
}

/** A small button for a flag or a clause, quieter than a page's own. */
export const small = "h-9 rounded-[10px] px-3 text-[13px]";
