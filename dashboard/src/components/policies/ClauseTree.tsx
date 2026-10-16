import {
  ArrowLeftRight,
  Heading,
  ListIndentDecrease,
  ListIndentIncrease,
  Merge,
  Pilcrow,
} from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";

import type { DraftClause, DraftFlag, Edit } from "@/api/policies";
import { Button } from "@/components/ui/button";
import { FIX_WORDS, isolate, shortKey } from "@/lib/policies";
import { cn } from "@/lib/utils";

import { FlagChip, small } from "./FlagCard";

type Layer = NonNullable<DraftClause["layer"]>;

const LAYERS: readonly Layer[] = ["native_structure", "typography", "numbering", "reviewer"];

/** Which evidence decided a clause, quietly: the file, its type, a number typed in, or you. */
function LayerChip({ layer }: { layer: Layer }) {
  const { t } = useTranslation();
  return (
    <span
      dir="ltr"
      className={cn(
        "rounded-[7px] px-[7px] py-1 font-mono text-xs leading-none font-medium whitespace-nowrap",
        layer === "reviewer" ? "bg-brand-soft text-brand-dark" : "bg-field text-muted",
      )}
    >
      {t(`review.layers.${layer}`)}
    </span>
  );
}

/** Why a clause is where it is, in the words of the evidence, or the reviewer, that put it there. */
function whyOf(t: TFunction, clause: DraftClause, parent: string): string {
  const layer = clause.layer ?? "native_structure";
  const read = layer === "reviewer" ? "native_structure" : layer;
  const label = isolate(clause.label ?? "");
  let why: string;
  if (layer === "reviewer" && clause.fixed) {
    why = t(`review.whyFixed.${FIX_WORDS[clause.fixed]}`, { key: parent });
  } else if (clause.kind === "list") {
    why = t("review.whyList");
  } else if (clause.kind === "table") {
    why = t("review.whyTable");
  } else if (clause.kind === "row") {
    why = t("review.whyRow");
  } else if (clause.heading) {
    why = t(`review.whyHeading.${read}`, { label });
  } else if (read === "native_structure" && clause.label) {
    why = t("review.whyParagraph.listed", { label });
  } else {
    why = t(`review.whyParagraph.${read}`, { label });
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
  parent: DraftClause | null;
  before: DraftClause | null;
}

function rowsOf(clauses: readonly DraftClause[], depth = 0, parent: DraftClause | null = null) {
  return clauses.flatMap((clause, index): Row[] => [
    { clause, depth, parent, before: clauses[index - 1] ?? null },
    ...rowsOf(clause.children, depth + 1, clause),
  ]);
}

/** A split under way: the clause, and where its second part begins once one is chosen. */
export interface Splitting {
  key: string;
  at: number | null;
}

/** What the tree needs to offer the fixing tools, for someone who may use them. */
export interface Fixing {
  busy: boolean;
  /** The fixes open flags suggest, by the clause each applies to. */
  suggested: ReadonlyMap<string, readonly Edit[]>;
  splitting: Splitting | null;
  onSplitting: (splitting: Splitting | null) => void;
  onFix: (edit: Edit, key: string, at?: number) => void;
}

function Tools({
  clause,
  before,
  slug,
  fixing,
}: {
  clause: DraftClause;
  before: DraftClause | null;
  slug: string;
  fixing: Fixing;
}) {
  const { t } = useTranslation();
  const suggested = fixing.suggested.get(clause.key) ?? [];
  const tool = (edit: Edit, icon: ReactNode, label: string, act: () => void) => (
    <Button
      size="sm"
      variant={suggested.includes(edit) ? "primary" : "quiet"}
      className={small}
      disabled={fixing.busy || !(clause.fixes ?? []).includes(edit)}
      onClick={act}
    >
      {icon}
      {label}
    </Button>
  );
  const fix = (edit: Edit) => () => fixing.onFix(edit, clause.key);
  const only = clause.splits?.length === 1 ? (clause.splits[0]?.at ?? null) : null;
  return (
    <div role="toolbar" aria-label={t("review.tools")} className="flex flex-wrap gap-2">
      {tool("split", <ArrowLeftRight aria-hidden className="size-4" />, t("review.split"), () =>
        fixing.onSplitting({ key: clause.key, at: only }),
      )}
      {tool("merge", <Merge aria-hidden className="size-4" />, t("review.merge"), fix("merge"))}
      {clause.kind === "section" && clause.heading !== null
        ? tool(
            "make-text",
            <Pilcrow aria-hidden className="size-4" />,
            t("review.makeText"),
            fix("make-text"),
          )
        : null}
      {clause.kind === "paragraph"
        ? tool(
            "make-heading",
            <Heading aria-hidden className="size-4" />,
            t("review.makeHeading"),
            fix("make-heading"),
          )
        : null}
      {tool(
        "move-under",
        <ListIndentIncrease aria-hidden className="size-4" />,
        before
          ? t("review.moveUnder", { key: isolate(shortKey(before.key, slug)) })
          : t("review.moveUnderNone"),
        fix("move-under"),
      )}
      {tool(
        "move-out",
        <ListIndentDecrease aria-hidden className="size-4" />,
        t("review.moveOut"),
        fix("move-out"),
      )}
    </div>
  );
}

/** The first words after a place to split, which name it to a screen reader. */
function wordsAfter(text: string, at: number): string {
  return text.slice(at).split(/\s+/).slice(0, 5).join(" ");
}

/** Board 4's split: the clause's text with every place it can be split, and what it becomes. */
function SplitBox({
  clause,
  slug,
  at,
  fixing,
  rtl,
}: {
  clause: DraftClause;
  slug: string;
  at: number | null;
  fixing: Fixing;
  rtl: boolean;
}) {
  const { t } = useTranslation();
  const text = clause.text;
  const places = clause.splits ?? [];
  const chosen = places.find((place) => place.at === at) ?? null;
  const title = `split-${clause.key}`;
  const pieces: ReactNode[] = [];
  let from = 0;
  for (const place of places) {
    pieces.push(text.slice(from, place.at));
    pieces.push(
      place.at === at ? (
        <span
          key={place.at}
          className="mx-1.5 inline-flex items-center gap-1 rounded-full bg-brand px-2 py-0.5 align-[2px] text-xs font-semibold text-white"
        >
          <ArrowLeftRight aria-hidden className="size-3" />
          {t("review.splitHere")}
        </span>
      ) : (
        <button
          key={place.at}
          type="button"
          aria-label={t("review.splitBefore", { words: wordsAfter(text, place.at) })}
          onClick={() => fixing.onSplitting({ key: clause.key, at: place.at })}
          className="mx-1 inline-grid size-5 place-items-center rounded-full border border-brand/40 align-[-3px] text-brand-dark hover:bg-brand-soft"
        >
          <ArrowLeftRight aria-hidden className="size-3" />
        </button>
      ),
    );
    from = place.at;
  }
  pieces.push(text.slice(from));
  const second = chosen ? text.slice(chosen.at).trimStart() : "";
  const secondWords = chosen?.label ? second.slice(chosen.label.length).trimStart() : second;
  const preview = (key: string, words: string) => (
    <div className="flex min-h-9 items-center gap-2.5 rounded-xl px-3 py-[3px]">
      <span className="min-w-13 shrink-0 font-mono text-[13px] font-medium whitespace-nowrap text-brand-dark">
        {key}
      </span>
      <span dir="auto" className="min-w-0 flex-1 truncate text-sm">
        {words}
      </span>
      <LayerChip layer="reviewer" />
    </div>
  );
  return (
    <div
      role="group"
      aria-labelledby={title}
      data-splitting
      className="flex flex-col gap-3 rounded-[14px] border-[1.5px] border-brand bg-white px-4 py-3.5"
    >
      <div id={title} className="text-[15px] font-semibold">
        {t("review.splitTitle", { key: isolate(shortKey(clause.key, slug)) })}
      </div>
      <p dir={rtl ? "rtl" : "auto"} className="text-[15px] leading-[1.75] whitespace-pre-line">
        {pieces}
      </p>
      {chosen ? (
        <>
          <p className="text-[13px] text-muted">
            {chosen.label ? t("review.splitNumbered") : t("review.splitPlain")}
          </p>
          <div className="rounded-xl bg-panel p-1.5">
            {preview(shortKey(clause.key, slug), text.slice(0, chosen.at).trimEnd())}
            {preview(chosen.label ?? t("review.newKey"), secondWords)}
          </div>
        </>
      ) : (
        <p className="text-[13px] text-muted">{t("review.splitChoose")}</p>
      )}
      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          className={small}
          disabled={!chosen || fixing.busy}
          onClick={() => {
            if (chosen) {
              fixing.onFix("split", clause.key, chosen.at);
            }
          }}
        >
          <ArrowLeftRight aria-hidden className="size-4" />
          {t("review.splitIt")}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className={small}
          onClick={() => fixing.onSplitting(null)}
        >
          {t("review.cancel")}
        </Button>
      </div>
    </div>
  );
}

/** The draft's clauses as the parser built them, each with its key and what decided it. */
export function ClauseTree({
  clauses,
  slug,
  selected,
  flags,
  rtl,
  onSelect,
  fixing,
}: {
  clauses: readonly DraftClause[];
  slug: string;
  selected: string | null;
  /** The open flags on each clause, by key. */
  flags: ReadonlyMap<string, DraftFlag[]>;
  rtl: boolean;
  onSelect: (key: string) => void;
  /** The fixing tools, for someone who may use them. */
  fixing?: Fixing;
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

  // A split opens under its clause, perhaps past the edge of the list: bring all of it in.
  const splitKey = fixing?.splitting?.key ?? null;
  useEffect(() => {
    if (splitKey) {
      box.current
        ?.querySelector<HTMLElement>("[data-splitting]")
        ?.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
    }
  }, [splitKey]);

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
        {rowsOf(clauses).map(({ clause, depth, parent, before }) => {
          const chosen = clause.key === selected;
          const words = clause.heading ?? clause.text.split("\n")[0] ?? "";
          const open = flags.get(clause.key) ?? [];
          const under = parent ? isolate(shortKey(parent.key, slug)) : "";
          const splitting = fixing?.splitting?.key === clause.key ? fixing.splitting : null;
          const note = clause.fixed
            ? t(`review.fixedNote.${FIX_WORDS[clause.fixed]}`, { key: under })
            : null;
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
                  {note ? (
                    <span
                      title={note}
                      className="hidden max-w-36 truncate text-[13px] text-muted sm:inline-block"
                    >
                      {note}
                    </span>
                  ) : null}
                  {open.map((flag) => (
                    <FlagChip key={flag.position}>{flag.position}</FlagChip>
                  ))}
                  <LayerChip layer={clause.layer ?? "native_structure"} />
                </span>
              </button>
              {chosen && splitting && fixing ? (
                <div className="mt-0.5 mb-2" style={{ marginInlineStart: 12 + depth * 24 }}>
                  <SplitBox
                    clause={clause}
                    slug={slug}
                    at={splitting.at}
                    fixing={fixing}
                    rtl={rtl}
                  />
                </div>
              ) : chosen ? (
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
                  <p className="text-[13px] leading-normal text-muted">{whyOf(t, clause, under)}</p>
                  {fixing ? (
                    <Tools clause={clause} before={before} slug={slug} fixing={fixing} />
                  ) : null}
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** Board 4's card: what each tool is for, and what a fix never changes. */
export function Toolbox() {
  const { t } = useTranslation();
  const card = (icon: ReactNode, title: string, text: string) => (
    <div className="flex items-start gap-3">
      <span className="grid size-9 shrink-0 place-items-center rounded-[10px] bg-brand-soft text-brand-dark">
        {icon}
      </span>
      <div>
        <div className="text-[15px] font-semibold">{title}</div>
        <p className="mt-0.5 text-sm leading-normal text-ink-2">{text}</p>
      </div>
    </div>
  );
  return (
    <section aria-labelledby="toolbox-heading" className="flex flex-col gap-4">
      <div>
        <h2 id="toolbox-heading" className="text-lg font-semibold">
          {t("review.toolbox")}
        </h2>
        <p className="mt-1.5 text-sm text-muted">{t("review.toolboxLead")}</p>
      </div>
      {card(
        <ArrowLeftRight aria-hidden className="size-[18px]" />,
        t("review.toolSplit"),
        t("review.toolSplitText"),
      )}
      {card(
        <Merge aria-hidden className="size-[18px]" />,
        t("review.toolMerge"),
        t("review.toolMergeText"),
      )}
      {card(
        <Heading aria-hidden className="size-[18px]" />,
        t("review.toolHeading"),
        t("review.toolHeadingText"),
      )}
      {card(
        <ListIndentIncrease aria-hidden className="size-[18px]" />,
        t("review.toolLevel"),
        t("review.toolLevelText"),
      )}
      <p className="border-t border-line pt-3.5 text-[13px] leading-relaxed text-muted">
        {t("review.toolboxNote")}
      </p>
    </section>
  );
}
