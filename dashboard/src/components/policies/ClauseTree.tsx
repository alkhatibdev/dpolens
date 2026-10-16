import { useEffect, useRef } from "react";
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";

import type { DraftClause, DraftFlag } from "@/api/policies";
import { isolate, shortKey } from "@/lib/policies";
import { cn } from "@/lib/utils";

import { FlagChip } from "./FlagCard";

type Layer = "native_structure" | "typography" | "numbering";

const LAYERS: readonly Layer[] = ["native_structure", "typography", "numbering"];

/** Which evidence decided a clause, quietly: the file, its type, or a number typed in. */
function LayerChip({ layer }: { layer: Layer }) {
  const { t } = useTranslation();
  return (
    <span
      dir="ltr"
      className="rounded-[7px] bg-field px-[7px] py-1 font-mono text-xs leading-none font-medium whitespace-nowrap text-muted"
    >
      {t(`review.layers.${layer}`)}
    </span>
  );
}

/** Why a clause is where it is, in the words of the evidence that put it there. */
function whyOf(t: TFunction, clause: DraftClause): string {
  const layer = clause.layer ?? "native_structure";
  const label = isolate(clause.label ?? "");
  let why: string;
  if (clause.kind === "list") {
    why = t("review.whyList");
  } else if (clause.kind === "table") {
    why = t("review.whyTable");
  } else if (clause.kind === "row") {
    why = t("review.whyRow");
  } else if (clause.heading) {
    why = t(`review.whyHeading.${layer}`, { label });
  } else if (layer === "native_structure" && clause.label) {
    why = t("review.whyParagraph.listed", { label });
  } else {
    why = t(`review.whyParagraph.${layer}`, { label });
  }
  const below = clause.children.length;
  return below ? `${why} ${t("review.holds", { count: below })}` : why;
}

function Legend() {
  const { t } = useTranslation();
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-[13px] text-muted">
      <span>{t("review.legend")}</span>
      {LAYERS.map((layer) => (
        <span key={layer} className="inline-flex items-center gap-1.5 whitespace-nowrap">
          <LayerChip layer={layer} />
          {t(`review.legendWords.${layer}`)}
        </span>
      ))}
    </div>
  );
}

interface Row {
  clause: DraftClause;
  depth: number;
}

function rowsOf(clauses: readonly DraftClause[], depth = 0): Row[] {
  return clauses.flatMap((clause) => [{ clause, depth }, ...rowsOf(clause.children, depth + 1)]);
}

/** The draft's clauses as the parser built them, each with its key and what decided it. */
export function ClauseTree({
  clauses,
  slug,
  selected,
  flags,
  rtl,
  onSelect,
}: {
  clauses: readonly DraftClause[];
  slug: string;
  selected: string | null;
  /** The open flags on each clause, by key. */
  flags: ReadonlyMap<string, DraftFlag[]>;
  rtl: boolean;
  onSelect: (key: string) => void;
}) {
  const { t } = useTranslation();
  const box = useRef<HTMLUListElement>(null);

  useEffect(() => {
    const scroller = box.current;
    const target = scroller?.querySelector<HTMLElement>("[aria-current='true']");
    if (!scroller || !target || scroller.scrollHeight <= scroller.clientHeight) {
      return;
    }
    const top =
      target.getBoundingClientRect().top -
      scroller.getBoundingClientRect().top +
      scroller.scrollTop;
    scroller.scrollTo?.({ top: Math.max(0, top - 48), behavior: "smooth" });
  }, [selected]);

  return (
    <section aria-labelledby="clauses-heading" className="flex min-w-0 flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2.5">
        <h2 id="clauses-heading" className="text-lg font-semibold">
          {t("review.clausesHeading")}
        </h2>
        <span className="text-[13px] text-muted">{t("review.selectHint")}</span>
      </div>
      <Legend />
      <ul ref={box} className="flex flex-col gap-0.5 lg:max-h-[78dvh] lg:overflow-y-auto">
        {rowsOf(clauses).map(({ clause, depth }) => {
          const chosen = clause.key === selected;
          const words = clause.heading ?? clause.text.split("\n")[0] ?? "";
          const open = flags.get(clause.key) ?? [];
          return (
            <li key={clause.key} className={cn(clause.heading && "mt-2 first:mt-0")}>
              <button
                type="button"
                aria-current={chosen ? "true" : undefined}
                onClick={() => onSelect(clause.key)}
                dir={rtl ? "rtl" : "ltr"}
                style={{ paddingInlineStart: 12 + depth * 24 }}
                className={cn(
                  "flex min-h-9 w-full items-center gap-2.5 rounded-xl py-[3px] pe-3 text-start hover:bg-field",
                  chosen &&
                    (rtl
                      ? "bg-brand-soft shadow-[inset_-3px_0_0_var(--color-brand)] hover:bg-brand-soft"
                      : "bg-brand-soft shadow-[inset_3px_0_0_var(--color-brand)] hover:bg-brand-soft"),
                )}
              >
                <span className="min-w-13 shrink-0 font-mono text-[13px] font-medium whitespace-nowrap text-brand-dark">
                  {shortKey(clause.key, slug)}
                </span>
                <span
                  dir="auto"
                  className={cn(
                    "min-w-0 flex-1 truncate text-sm",
                    clause.heading ? "font-semibold" : "font-normal",
                  )}
                >
                  {words}
                </span>
                <span dir="ltr" className="inline-flex shrink-0 items-center gap-1.5">
                  {open.map((flag) => (
                    <FlagChip key={flag.position}>{flag.position}</FlagChip>
                  ))}
                  <LayerChip layer={clause.layer ?? "native_structure"} />
                </span>
              </button>
              {chosen ? (
                <div
                  className="mt-0.5 mb-2 flex flex-col gap-2.5 rounded-[14px] border border-line bg-white px-4 py-3.5"
                  style={{ marginInlineStart: 12 + depth * 24 }}
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-[13px] text-muted">{t("review.key")}</span>
                    <span
                      dir="auto"
                      className="font-mono text-[13px] font-medium break-all text-brand-dark"
                    >
                      {clause.key}
                    </span>
                  </div>
                  <div dir="auto" className="text-[15px] leading-relaxed whitespace-pre-line">
                    {clause.heading ? (
                      <strong className="font-semibold">{clause.heading}</strong>
                    ) : null}
                    {clause.heading && clause.text ? "\n" : null}
                    {clause.text}
                  </div>
                  <p className="text-[13px] leading-normal text-muted">{whyOf(t, clause)}</p>
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
