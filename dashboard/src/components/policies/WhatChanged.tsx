import { Check, History } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { useClauseActivity } from "@/api/logs";
import type { DraftClause, DraftFlag, PolicyDraft, PolicySummary } from "@/api/policies";
import { Chip } from "@/components/States";
import { Button } from "@/components/ui/button";
import { formatDate } from "@/lib/format";
import { QUERIES_READ_ALL } from "@/lib/permissions";
import { isolate, shortKey, walk } from "@/lib/policies";
import { wordDiff } from "@/lib/wordDiff";
import { usePermitted } from "@/session";

import { FlagCard, small } from "./FlagCard";

export function Stat({ value, label, note }: { value: ReactNode; label: string; note: string }) {
  return (
    <div className="min-w-0 flex-[1_1_160px]">
      <div className="text-[13px] text-muted">{label}</div>
      <div className="mt-1 text-[22px] font-semibold tracking-[-0.01em] tabular-nums">{value}</div>
      <div className="mt-0.5 text-[13px] leading-snug text-muted">{note}</div>
    </div>
  );
}

/** A clause's new words beside its old ones: what was added marked, what was taken away struck. */
function Reworded({ before, after }: { before: string; after: string }) {
  return (
    <>
      {wordDiff(before, after).map((piece, at) => {
        const space = /^\s/.test(piece.text) ? " " : "";
        const text = piece.text.trimStart();
        if (piece.change === "added") {
          return (
            <span key={at}>
              {space}
              <ins className="rounded bg-brand-soft px-0.5 font-semibold text-brand-dark no-underline">
                {text}
              </ins>
            </span>
          );
        }
        if (piece.change === "removed") {
          return (
            <span key={at}>
              {space}
              <del className="rounded bg-danger-soft px-0.5 text-danger-ink">{text}</del>
            </span>
          );
        }
        return <span key={at}>{piece.text}</span>;
      })}
    </>
  );
}

/** How often the earlier clause was cited this week, for whoever may read every question. */
function Cited({
  earlierKey,
  slug,
  previous,
}: {
  earlierKey: string;
  slug: string;
  previous: string;
}) {
  const { t } = useTranslation();
  const can = usePermitted();
  const allowed = can.has(QUERIES_READ_ALL);
  const activity = useClauseActivity(earlierKey, allowed);
  const total = activity.data?.total ?? 0;
  if (!allowed || total === 0) {
    return null;
  }
  return (
    <div className="flex items-start gap-2 text-[13px] leading-normal text-muted">
      <History aria-hidden className="mt-0.5 size-[15px] shrink-0" />
      {t("changes.cited", {
        count: total,
        label: isolate(previous),
        key: isolate(shortKey(earlierKey, slug)),
      })}
    </div>
  );
}

function reworded(clause: DraftClause): boolean {
  const earlier = clause.earlier;
  return earlier !== null && (earlier.text !== clause.text || earlier.heading !== clause.heading);
}

/** A clause's words, with what changed since the clause it continues marked. */
export function Words({ clause }: { clause: Pick<DraftClause, "heading" | "text" | "earlier"> }) {
  const earlier = clause.earlier;
  const headingChanged = earlier !== null && earlier.heading !== clause.heading;
  return (
    <div dir="auto" className="flex flex-col gap-1 text-[15px] leading-relaxed">
      {clause.heading ? (
        <p className="font-semibold">
          {headingChanged ? (
            <Reworded before={earlier?.heading ?? ""} after={clause.heading} />
          ) : (
            clause.heading
          )}
        </p>
      ) : null}
      {clause.text ? (
        <p className="whitespace-pre-line">
          {earlier && earlier.text !== clause.text ? (
            <Reworded before={earlier.text} after={clause.text} />
          ) : (
            clause.text
          )}
        </p>
      ) : null}
    </div>
  );
}

export function ChangeRow({
  keyText,
  keyNote,
  chips,
  children,
}: {
  keyText: string;
  /** Which version the number belongs to, when it is not the draft's. */
  keyNote?: string;
  chips: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-x-3.5 gap-y-2 border-b border-line px-1 py-[18px] last:border-b-0 sm:grid-cols-[92px_minmax(0,1fr)]">
      <div className="pt-0.5">
        <div className="font-mono text-[13px] font-medium break-words text-brand-dark">
          {keyText.split(":").map((part, at) => (
            // A long key wraps where its parts meet, not in the middle of one.
            <span key={at}>
              {at ? (
                <>
                  :<wbr />
                </>
              ) : null}
              {part}
            </span>
          ))}
        </div>
        {keyNote ? <div className="mt-0.5 text-xs text-muted">{keyNote}</div> : null}
      </div>
      <div className="flex min-w-0 flex-col gap-2.5">
        <div className="flex flex-wrap gap-2">{chips}</div>
        {children}
      </div>
    </div>
  );
}

/**
 * A new version against the one before it: every clause that is new, renumbered,
 * reworded or removed, and each match the parser made for the reviewer to confirm.
 */
export function WhatChanged({
  draft,
  summary,
  canSettle,
  busy,
  onAccept,
  onReject,
}: {
  draft: PolicyDraft;
  summary: PolicySummary | undefined;
  canSettle: boolean;
  busy: boolean;
  onAccept: (flag: DraftFlag) => void;
  onReject: (clause: DraftClause) => void;
}) {
  const { t } = useTranslation();
  const slug = draft.version.slug;
  const previous = draft.previous ?? "";
  const clauses = walk(draft.clauses);
  const changed = clauses.filter((clause) => clause.change && clause.change !== "unchanged");
  const unchanged = clauses.filter((clause) => clause.change === "unchanged");
  const flagOn = new Map(
    draft.flags
      .filter((flag) => flag.kind === "unmatched_key" && flag.key)
      .map((flag) => [flag.key ?? "", flag]),
  );
  const counts = draft.changes;
  const movedReworded = clauses.filter((clause) => clause.change === "moved" && reworded(clause));

  const heading =
    summary?.in_force === previous && summary.in_force_since
      ? t("changes.against", { label: previous, date: formatDate(summary.in_force_since) })
      : summary?.scheduled?.label === previous
        ? t("changes.againstScheduled", {
            label: previous,
            date: formatDate(summary.scheduled.effective_date),
          })
        : t("changes.againstPlain", { label: previous });

  function chipsOf(clause: DraftClause) {
    const was = isolate(shortKey(clause.continues ?? "", slug));
    switch (clause.change) {
      case "added":
        return <Chip tone="brand">{t("changes.chipAdded")}</Chip>;
      case "moved":
        return reworded(clause) ? (
          <Chip tone="soft">{t("changes.chipMovedReworded", { key: was })}</Chip>
        ) : (
          <>
            <Chip tone="soft">{t("changes.chipMoved", { key: was })}</Chip>
            <Chip tone="quiet">{t("changes.chipSameWords")}</Chip>
          </>
        );
      default:
        return <Chip tone="soft">{t("changes.chipModified")}</Chip>;
    }
  }

  function actionsFor(clause: DraftClause, flag: DraftFlag) {
    if (!canSettle) {
      return null;
    }
    if (clause.change === "added") {
      return (
        <Button size="sm" className={small} disabled={busy} onClick={() => onAccept(flag)}>
          <Check aria-hidden className="size-4" />
          {t("changes.acceptReuse")}
        </Button>
      );
    }
    return (
      <>
        <Button size="sm" className={small} disabled={busy} onClick={() => onAccept(flag)}>
          <Check aria-hidden className="size-4" />
          {t("changes.sameRule")}
        </Button>
        <Button
          size="sm"
          variant="quiet"
          className={small}
          disabled={busy}
          onClick={() => onReject(clause)}
        >
          {t("changes.differentRule")}
        </Button>
      </>
    );
  }

  return (
    <>
      <section
        className="rounded-[20px] bg-white px-[22px] py-[18px]"
        aria-labelledby="changes-heading"
      >
        <h2 id="changes-heading" className="text-lg font-semibold">
          {heading}
        </h2>
        <div className="mt-3.5 flex flex-wrap gap-[18px]">
          <Stat
            value={counts.added || t("changes.none")}
            label={t("changes.added")}
            note={t("changes.addedNote", { label: previous })}
          />
          <Stat
            value={counts.moved || t("changes.none")}
            label={t("changes.moved")}
            note={
              !movedReworded.length
                ? t("changes.movedNote")
                : movedReworded.length === counts.moved
                  ? t("changes.movedAllReworded")
                  : t("changes.movedReworded", { count: movedReworded.length })
            }
          />
          {counts.modified ? (
            <Stat
              value={counts.modified}
              label={t("changes.modified")}
              note={t("changes.modifiedNote")}
            />
          ) : null}
          <Stat
            value={counts.unchanged || t("changes.none")}
            label={t("changes.unchanged")}
            note={t("changes.unchangedNote")}
          />
          <Stat
            value={counts.removed || t("changes.none")}
            label={t("changes.removed")}
            note={
              counts.removed
                ? t("changes.removedNote", { label: previous })
                : t("changes.removedNone", { label: previous })
            }
          />
        </div>
        <div className="mt-4 flex items-start gap-3 rounded-[14px] bg-brand-soft px-4 py-3.5">
          <History aria-hidden className="mt-0.5 size-5 shrink-0 text-brand-dark" />
          <p className="text-sm leading-relaxed text-ink">
            {t("changes.keysNote", { label: previous })}
          </p>
        </div>
      </section>

      <section className="rounded-[20px] bg-white px-[22px] pt-1.5 pb-3">
        {changed.length === 0 && draft.removed.length === 0 ? (
          <p className="py-5 text-[15px] text-muted">{t("changes.nothing")}</p>
        ) : null}
        {changed.map((clause) => {
          const flag = flagOn.get(clause.key);
          return (
            <ChangeRow
              key={clause.key}
              keyText={shortKey(clause.key, slug)}
              chips={chipsOf(clause)}
            >
              <Words clause={clause} />
              {clause.change === "moved" && clause.continues ? (
                <Cited earlierKey={clause.continues} slug={slug} previous={previous} />
              ) : null}
              {flag ? (
                <FlagCard flag={flag} slug={slug} compact actions={actionsFor(clause, flag)} />
              ) : null}
            </ChangeRow>
          );
        })}
        {draft.removed.map((gone) => (
          <ChangeRow
            key={gone.key}
            keyText={shortKey(gone.key, slug)}
            keyNote={t("changes.inVersion", { label: isolate(previous) })}
            chips={<Chip tone="quiet">{t("changes.chipRemoved")}</Chip>}
          >
            <div dir="auto" className="flex flex-col gap-1 text-[15px] leading-relaxed text-ink-2">
              {gone.heading ? <p className="font-semibold">{gone.heading}</p> : null}
              {gone.text ? <p className="whitespace-pre-line">{gone.text}</p> : null}
            </div>
          </ChangeRow>
        ))}
        {unchanged.length ? (
          <details className="px-1 pt-4 pb-1.5">
            <summary className="cursor-pointer text-[15px] font-semibold">
              {t("changes.unchangedList", { count: unchanged.length })}
            </summary>
            <p className="mt-2 text-sm leading-relaxed text-muted">
              {unchanged
                .map((clause) =>
                  [shortKey(clause.key, slug), clause.heading].filter(Boolean).join(" "),
                )
                .join(", ")}
            </p>
          </details>
        ) : null}
      </section>
    </>
  );
}
