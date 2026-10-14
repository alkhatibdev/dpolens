import { useTranslation } from "react-i18next";

import type { Clause } from "@/api/client";
import { isRightToLeft, languageName, readingOrder } from "@/lib/format";
import { cn } from "@/lib/utils";

import { KeyButton } from "./CopyCitation";

interface Row {
  key: string;
  depth: number;
  texts: Record<string, Clause>;
  leads: boolean;
}

function rowsOf(byLanguage: Record<string, Clause[]>, languages: string[]): Row[] {
  const first = languages.map((lang) => byLanguage[lang] ?? []).find((list) => list.length) ?? [];
  const rows = first.map((clause, index) => ({
    key: clause.key,
    depth: clause.depth,
    texts: Object.fromEntries(
      languages.flatMap((lang) => {
        const match = (byLanguage[lang] ?? []).find((other) => other.key === clause.key);
        return match ? [[lang, match]] : [];
      }),
    ) as Record<string, Clause>,
    leads: (first[index + 1]?.depth ?? -1) > clause.depth,
  }));
  return rows;
}

function hasText(row: Row): boolean {
  return Object.values(row.texts).some((clause) => clause.text.trim());
}

/** The clauses above a row, inside what is shown, for its citation. */
function ancestorsOf(rows: Row[], index: number, lang: string): Clause[] {
  const trail: Clause[] = [];
  let depth = rows[index]?.depth ?? 0;
  for (let at = index - 1; at >= 0; at -= 1) {
    const row = rows[at];
    if (row && row.depth < depth) {
      const clause = row.texts[lang];
      if (clause) {
        trail.unshift(clause);
      }
      depth = row.depth;
    }
  }
  return trail;
}

/**
 * A clause and its points, each language in its own column with the key between
 * them; on a phone, one language under the other.
 */
export function Reading({
  byLanguage,
  languages,
  breadcrumb,
}: {
  byLanguage: Record<string, Clause[]>;
  languages: readonly string[];
  /** The clauses above the first one shown, for the citations. */
  breadcrumb: readonly Clause[];
}) {
  const { t } = useTranslation();
  const order = readingOrder(languages);
  // Every clause counts for a citation's trail; only those with words get a row.
  const all = rowsOf(byLanguage, order);
  const rows = all.filter(hasText);
  const base = rows[0]?.depth ?? 0;
  const two = order.length > 1;
  const columns = two
    ? "md:grid-cols-[minmax(0,1fr)_76px_minmax(0,1fr)]"
    : "md:grid-cols-[minmax(0,1fr)_76px]";

  function textCell(clause: Clause | undefined, lang: string, row: Row) {
    if (!clause) {
      return <div />;
    }
    const indent = Math.max(0, row.depth - base) * 18;
    return (
      <p
        lang={lang}
        dir={isRightToLeft(lang) ? "rtl" : "ltr"}
        style={{ paddingInlineStart: indent }}
        className={cn(
          "text-[15px] leading-relaxed sm:text-base",
          isRightToLeft(lang) && "text-[16px] sm:text-[17px]",
          row.leads && "font-medium",
          lang !== order[0] && "rounded-xl bg-field px-3 py-2 md:bg-transparent md:px-0 md:py-0",
        )}
      >
        {clause.label ? <span className="font-semibold">{clause.label} </span> : null}
        {clause.text}
      </p>
    );
  }

  return (
    <div>
      {two ? (
        <div
          className={cn(
            "hidden gap-x-[18px] border-b border-line py-3 text-[13px] text-muted md:grid",
            columns,
          )}
        >
          {order.map((lang, index) => {
            const sample = byLanguage[lang]?.[0];
            const prevails = sample?.is_authoritative;
            const heading = (
              <span key={lang} className={cn(prevails && "font-semibold text-brand-dark")}>
                {languageName(lang)},{" "}
                {prevails ? t("clause.authoritative") : t("clause.translation")}
              </span>
            );
            return index === 0
              ? [
                  heading,
                  <span key="key" className="text-center">
                    {t("clause.key")}
                  </span>,
                ]
              : heading;
          })}
        </div>
      ) : null}
      {rows.map((row) => {
        const citing = row.texts[order[0] ?? ""] ?? Object.values(row.texts)[0];
        const key = citing ? (
          <div className="flex md:justify-center">
            <KeyButton
              clause={citing}
              breadcrumb={[...breadcrumb, ...ancestorsOf(all, all.indexOf(row), citing.lang)]}
              label={row.key.split(":").pop() ?? row.key}
              emphasis={row.depth === base}
            />
          </div>
        ) : (
          <div />
        );
        return (
          <div
            key={row.key}
            id={row.key}
            className={cn(
              "flex scroll-mt-24 flex-col gap-2 border-b border-line py-3.5 last:border-b-0 md:grid md:items-start md:gap-x-[18px] md:gap-y-0",
              columns,
            )}
          >
            {textCell(row.texts[order[0] ?? ""], order[0] ?? "", row)}
            <div className="order-first md:order-none">{key}</div>
            {two ? textCell(row.texts[order[1] ?? ""], order[1] ?? "", row) : null}
          </div>
        );
      })}
    </div>
  );
}
