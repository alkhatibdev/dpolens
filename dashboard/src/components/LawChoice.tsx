import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import type { LoadedLaw } from "@/api/client";
import { LanguageChips } from "@/components/LanguageChips";
import { Chip } from "@/components/States";
import { Checkbox } from "@/components/ui/checkbox";
import { formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * A loaded law to tick: whose law it is, its languages, what it holds and, unless
 * compact, how far it has been checked and where to read it.
 */
export function LawChoice({
  law,
  checked,
  onChange,
  disabled = false,
  compact = false,
}: {
  law: LoadedLaw;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  compact?: boolean;
}) {
  const { t } = useTranslation();
  const id = `law-${law.slug}`;
  const facts: [string, string][] = [
    [t("laws.articles"), String(law.articles)],
    ...(law.recitals ? [[t("laws.recitals"), String(law.recitals)] as [string, string]] : []),
    [t("laws.inForce"), formatDate(law.effective_date, "short")],
    [t("laws.version"), law.version],
  ];
  return (
    <label
      htmlFor={id}
      className={cn(
        "flex min-w-0 cursor-pointer flex-col gap-3.5 rounded-[20px] border-2 bg-white p-5 sm:px-[22px]",
        checked ? "border-brand" : "border-line",
        disabled && "cursor-not-allowed opacity-60",
      )}
    >
      <span className="flex items-start justify-between gap-3">
        <span className="min-w-0">
          <span className="block text-sm text-muted">
            {law.jurisdiction} · {t("laws.law")}
          </span>
          <span
            id={`${id}-name`}
            className={cn(
              "mt-1 block leading-snug font-semibold",
              compact ? "text-[19px]" : "text-[19px] sm:text-[21px]",
            )}
          >
            {law.name}
          </span>
        </span>
        <Checkbox
          id={id}
          checked={checked}
          disabled={disabled}
          onCheckedChange={(value) => onChange(value === true)}
          aria-labelledby={`${id}-name`}
          className="mt-0.5 size-6 rounded-lg"
        />
      </span>
      <LanguageChips languages={law.languages} authoritative={law.authoritative_language} />
      <dl className="grid grid-cols-[repeat(auto-fit,minmax(104px,1fr))] gap-3">
        {facts.map(([label, value]) => (
          <div key={label}>
            <dt className="text-xs text-muted">{label}</dt>
            <dd className="text-base font-semibold tabular-nums">{value}</dd>
          </div>
        ))}
      </dl>
      {compact ? null : (
        <span className="mt-auto flex flex-wrap items-center justify-between gap-2.5 border-t border-line pt-3.5">
          <Chip tone="plain">{t(`laws.tiers.${law.trust_tier}`)}</Chip>
          {law.document ? (
            <Link
              to={`/library/${law.document}`}
              className="text-sm font-medium text-brand-dark underline underline-offset-2"
            >
              {t("laws.read")}
            </Link>
          ) : null}
        </span>
      )}
    </label>
  );
}
