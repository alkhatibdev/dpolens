import { Download, FileText, Flag } from "lucide-react";
import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

import type { FileParagraph, PolicyFile } from "@/api/policies";
import { Failed, Loading } from "@/components/States";
import { download } from "@/lib/download";
import { formatSize } from "@/lib/policies";
import { cn } from "@/lib/utils";

/** The translation key for each reason a paragraph is set aside. */
const REASONS = {
  title: "title",
  "front matter": "frontMatter",
  contents: "contents",
  "text box": "textBox",
  "repeated table": "repeatedTable",
} as const;

type Block =
  | { kind: "line"; line: FileParagraph }
  | { kind: "table"; index: number; rows: FileParagraph[][][] };

/** The paragraphs in order, a table's cells gathered back into its rows and columns. */
function blocksOf(paragraphs: readonly FileParagraph[]): Block[] {
  const blocks: Block[] = [];
  for (const line of paragraphs) {
    const last = blocks[blocks.length - 1];
    if (line.table === null || line.row === null || line.cell === null) {
      blocks.push({ kind: "line", line });
      continue;
    }
    const table =
      last?.kind === "table" && last.index === line.table
        ? last
        : { kind: "table" as const, index: line.table, rows: [] as FileParagraph[][][] };
    if (table !== last) {
      blocks.push(table);
    }
    const row = (table.rows[line.row] ??= []);
    (row[line.cell] ??= []).push(line);
  }
  return blocks;
}

export interface Marks {
  lit: ReadonlySet<string>;
  flagged: ReadonlySet<string>;
  flaggedParagraphs: ReadonlySet<number>;
}

/** Every clause that holds part of a paragraph: two, once a clause is split inside it. */
function holders(line: FileParagraph): string[] {
  return line.clauses?.length ? line.clauses : line.clause ? [line.clause] : [];
}

function isLit(line: FileParagraph, marks: Marks): boolean {
  return holders(line).some((key) => marks.lit.has(key));
}

function isFlagged(line: FileParagraph, marks: Marks): boolean {
  return (
    holders(line).some((key) => marks.flagged.has(key)) ||
    marks.flaggedParagraphs.has(line.position)
  );
}

function FlagMark() {
  const { t } = useTranslation();
  return (
    <span
      role="img"
      aria-label={t("review.flagged")}
      className="absolute top-2.5 grid size-[18px] place-items-center rounded-full bg-warn-soft text-warn-ink"
      style={{ insetInlineStart: -27 }}
    >
      <Flag aria-hidden className="size-[11px]" />
    </span>
  );
}

function Line({
  line,
  marks,
  rtl,
  onSelect,
}: {
  line: FileParagraph;
  marks: Marks;
  rtl: boolean;
  onSelect: (key: string) => void;
}) {
  const { t } = useTranslation();
  const lit = isLit(line, marks);
  const title = line.set_aside === "title" || line.title;
  return (
    <div
      data-lit={lit || undefined}
      onClick={line.clause ? () => onSelect(line.clause ?? "") : undefined}
      className={cn(
        "relative my-0.5 rounded-[10px] px-2.5 py-1.5",
        line.clause && "cursor-pointer hover:bg-white",
        line.set_aside && "border border-dashed border-line-strong",
        lit &&
          (rtl
            ? "bg-brand-soft shadow-[inset_-3px_0_0_var(--color-brand)] hover:bg-brand-soft"
            : "bg-brand-soft shadow-[inset_3px_0_0_var(--color-brand)] hover:bg-brand-soft"),
      )}
    >
      {isFlagged(line, marks) ? <FlagMark /> : null}
      {line.set_aside ? (
        <span
          dir="ltr"
          className="mb-1 block text-start text-[11px] font-semibold tracking-[0.08em] text-muted uppercase"
        >
          {t("review.setAside", { reason: t(`review.reasons.${REASONS[line.set_aside]}`) })}
        </span>
      ) : null}
      <p
        dir="auto"
        className={cn(
          "leading-relaxed",
          title ? "text-xl font-semibold" : line.heading ? "text-[15px] font-semibold" : "text-sm",
          line.bold && "font-semibold",
          line.set_aside ? "text-muted" : "text-ink",
        )}
      >
        {line.label ? <span className="text-muted">{line.label} </span> : null}
        {line.text}
      </p>
    </div>
  );
}

function TableBlock({
  rows,
  marks,
  onSelect,
}: {
  rows: FileParagraph[][][];
  marks: Marks;
  onSelect: (key: string) => void;
}) {
  return (
    <div className="my-2 overflow-x-auto rounded-[10px] border border-line bg-white">
      <table className="w-full border-collapse text-sm">
        <tbody>
          {rows.map((cells, at) => {
            const first = cells.find((cell) => cell?.length)?.[0];
            const lit = first ? isLit(first, marks) : false;
            const Cell = first?.header ? "th" : "td";
            return (
              <tr
                key={at}
                data-lit={lit || undefined}
                onClick={first?.clause ? () => onSelect(first.clause ?? "") : undefined}
                className={cn(
                  "border-b border-line last:border-b-0",
                  first?.clause && "cursor-pointer",
                  lit && "bg-brand-soft",
                  first?.set_aside && "text-muted",
                )}
              >
                {cells.map((cell, column) => (
                  <Cell
                    key={column}
                    dir="auto"
                    className="relative px-3 py-2 text-start align-top font-normal first:font-medium"
                  >
                    {column === 0 && first && isFlagged(first, marks) ? <FlagMark /> : null}
                    {(cell ?? []).map((line) => line.text).join("\n")}
                  </Cell>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** The file side of the review: every paragraph in order, as DPOLens read it. */
export function FileAsRead({
  file,
  failed,
  onRetry,
  slug,
  number,
  selected,
  marks,
  rtl,
  onSelect,
}: {
  file: PolicyFile | undefined;
  failed: boolean;
  onRetry: () => void;
  slug: string;
  number: number;
  /** The selected clause, whose paragraphs are brought into view. */
  selected: string | null;
  marks: Marks;
  rtl: boolean;
  onSelect: (key: string) => void;
}) {
  const { t } = useTranslation();
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const scroller = box.current;
    const target = scroller?.querySelector<HTMLElement>("[data-lit]");
    if (!scroller || !target || scroller.scrollHeight <= scroller.clientHeight) {
      return;
    }
    const top =
      target.getBoundingClientRect().top -
      scroller.getBoundingClientRect().top +
      scroller.scrollTop;
    scroller.scrollTo?.({ top: Math.max(0, top - 48), behavior: "smooth" });
  }, [selected]);

  const source = file?.source;
  return (
    <section aria-label={t("review.fileHeading")} className="flex min-w-0 flex-col gap-3.5">
      <div className="flex flex-wrap items-center justify-between gap-2.5">
        <div className="flex min-w-0 items-center gap-2.5">
          <FileText aria-hidden className="size-[18px] shrink-0 text-brand-dark" />
          <span dir="auto" className="text-[15px] font-semibold break-words">
            {source?.name ?? ""}
          </span>
          {source?.size ? (
            <span className="text-[13px] whitespace-nowrap text-muted">
              {t("review.fileSize", {
                kind: t(source.format === "docx" ? "review.word" : "review.markdown"),
                size: formatSize(source.size),
              })}
            </span>
          ) : null}
        </div>
        <button
          type="button"
          onClick={() => void download(`/v1/policies/${slug}/versions/${number}/original`)}
          className="inline-flex items-center gap-1.5 text-sm font-medium text-brand-dark hover:underline"
        >
          <Download aria-hidden className="size-4" />
          {t("review.download")}
        </button>
      </div>
      {failed ? <Failed onRetry={onRetry} /> : null}
      {!file && !failed ? <Loading /> : null}
      {file ? (
        <div
          ref={box}
          dir={rtl ? "rtl" : "ltr"}
          className="rounded-2xl border border-line bg-panel py-5 ps-10 pe-5 lg:max-h-[78dvh] lg:overflow-y-auto"
        >
          {blocksOf(file.paragraphs).map((block, at) =>
            block.kind === "line" ? (
              <Line
                key={block.line.position}
                line={block.line}
                marks={marks}
                rtl={rtl}
                onSelect={onSelect}
              />
            ) : (
              <TableBlock
                key={`table-${block.index}-${at}`}
                rows={block.rows}
                marks={marks}
                onSelect={onSelect}
              />
            ),
          )}
        </div>
      ) : null}
    </section>
  );
}
