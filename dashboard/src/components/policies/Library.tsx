import { Download, Flag, GitCompareArrows, History } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import type { VersionEntry } from "@/api/policies";
import { Chip } from "@/components/States";
import { Button } from "@/components/ui/button";
import { formatDate, formatWhen } from "@/lib/format";
import { isolate, originalOf, readingLink } from "@/lib/policies";
import { cn } from "@/lib/utils";

import { small } from "./FlagCard";

/** A draft of the policy is open: how far its review has got, and the way back to it. */
export function DraftBanner({ slug, draft }: { slug: string; draft: VersionEntry }) {
  const { t } = useTranslation();
  const label = isolate(draft.label);
  const open = draft.open ?? 0;
  return (
    <div
      role="note"
      className="flex flex-wrap items-center gap-3.5 rounded-[18px] bg-warn-soft px-[18px] py-3.5"
    >
      <Flag aria-hidden className="size-5 shrink-0 text-warn-ink" />
      <p className="min-w-0 flex-[1_1_420px] text-[15px] leading-normal text-warn-ink">
        <strong className="font-semibold">
          {open ? t("document.draft", { label, count: open }) : t("document.draftReady", { label })}
        </strong>{" "}
        {draft.created_by
          ? t("document.draftUploaded", {
              when: formatWhen(draft.created_at),
              name: draft.created_by,
            })
          : t("document.draftUploadedAnon", { when: formatWhen(draft.created_at) })}{" "}
        {t("document.draftTakesEffect", { date: formatDate(draft.effective_date) })}
      </p>
      <Button asChild variant="dark" size="sm">
        <Link to={`/policies/${encodeURIComponent(slug)}/draft`}>
          {t("document.continueReview")}
        </Link>
      </Button>
    </div>
  );
}

/** Reading a version that is not the one in force, and the way to the one that is. */
export function OldVersionBanner({ slug, entry }: { slug: string; entry: VersionEntry }) {
  const { t } = useTranslation();
  const label = isolate(entry.label);
  return (
    <div
      role="note"
      className="flex flex-wrap items-center gap-3.5 rounded-[20px] bg-brand-soft px-5 py-[18px]"
    >
      <History aria-hidden className="size-[22px] shrink-0 text-brand-dark" />
      <p className="min-w-0 flex-[1_1_460px] text-base font-semibold text-brand-dark">
        {entry.state === "scheduled"
          ? t("document.readingScheduled", { label, date: formatDate(entry.effective_date) })
          : t("document.readingOld", {
              label,
              from: formatDate(entry.effective_date),
              until: entry.until ? formatDate(entry.until) : "",
            })}
      </p>
      <Button asChild size="sm">
        <Link to={`/library/${encodeURIComponent(slug)}`}>{t("document.readInForce")}</Link>
      </Button>
    </div>
  );
}

function When({ entry }: { entry: VersionEntry }) {
  const { t } = useTranslation();
  const date = formatDate(entry.effective_date);
  switch (entry.state) {
    case "draft":
      return t("document.whenDraft", { date });
    case "scheduled":
      return t("document.whenScheduled", { date });
    case "in_force":
      return entry.until
        ? t("document.whenInForceUntil", { date, until: formatDate(entry.until) })
        : t("document.whenInForce", { date });
    case "replaced":
      return t("document.whenReplaced", {
        from: date,
        until: entry.until ? formatDate(entry.until) : "",
      });
  }
}

function Who({ entry }: { entry: VersionEntry }) {
  const { t } = useTranslation();
  if (entry.state === "draft") {
    return entry.created_by
      ? t("document.uploadedBy", { when: formatWhen(entry.created_at), name: entry.created_by })
      : t("document.uploadedAnon", { when: formatWhen(entry.created_at) });
  }
  const date = formatDate(entry.published_at ?? entry.created_at);
  return entry.published_by
    ? t("document.publishedBy", { date, name: entry.published_by })
    : t("document.publishedAnon", { date });
}

/**
 * Every version of the policy: the draft for those who review, the one in force, one
 * scheduled, and those replaced, each readable as it stood, with its original file.
 */
export function Versions({
  slug,
  versions,
  reading,
}: {
  slug: string;
  versions: readonly VersionEntry[];
  /** The number of the version on the page. */
  reading: number | null;
}) {
  const { t } = useTranslation();
  const published = versions.filter((entry) => entry.state !== "draft");
  return (
    <section
      aria-labelledby="versions-heading"
      className="rounded-[20px] bg-white px-[22px] pt-[18px] pb-2"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="versions-heading" className="text-xl font-semibold">
          {t("document.versions")}
        </h2>
        {published.length > 1 ? (
          <Button asChild variant="quiet" size="sm" className={small}>
            <Link to={`/library/${encodeURIComponent(slug)}/compare`}>
              <GitCompareArrows aria-hidden className="size-4" />
              {t("document.compare")}
            </Link>
          </Button>
        ) : null}
      </div>
      <ul className="mt-1.5">
        {versions.map((entry, index) => {
          const name = t("document.versionName", { label: isolate(entry.label) });
          const current = entry.state === "in_force";
          return (
            <li
              key={entry.number}
              aria-current={entry.number === reading ? "true" : undefined}
              className={cn(
                "grid grid-cols-1 items-center gap-x-3.5 gap-y-1 py-3.5 sm:grid-cols-[140px_minmax(0,1.2fr)_minmax(0,1.4fr)_auto]",
                index < versions.length - 1 && "border-b border-line",
              )}
            >
              <div className="flex flex-col items-start gap-1">
                {entry.state === "draft" || entry.number === reading ? (
                  <span className="text-base font-semibold">{name}</span>
                ) : (
                  <Link
                    to={readingLink(slug, entry, current)}
                    aria-label={t("document.readVersion", { label: entry.label })}
                    className="text-base font-semibold text-brand-dark hover:underline"
                  >
                    {name}
                  </Link>
                )}
                {entry.state === "replaced" ? (
                  <span className="text-xs text-muted">{t("document.states.replaced")}</span>
                ) : (
                  <Chip tone={entry.state === "draft" ? "warn" : "soft"}>
                    {t(`document.states.${entry.state}`)}
                  </Chip>
                )}
              </div>
              <span className="text-sm text-ink-2">
                <When entry={entry} />
              </span>
              <span className="text-sm text-muted">
                <Who entry={entry} />
              </span>
              <div className="sm:justify-self-end">
                {entry.state === "draft" ? (
                  <Button asChild variant="quiet" size="sm" className={small}>
                    <Link to={`/policies/${encodeURIComponent(slug)}/draft`}>
                      {t("document.continueReview")}
                    </Link>
                  </Button>
                ) : (
                  <Button asChild variant="ghost" size="sm" className={small}>
                    <a
                      href={originalOf(slug, entry)}
                      aria-label={t("document.originalOf", { label: entry.label })}
                    >
                      <Download aria-hidden className="size-4" />
                      {t("document.original")}
                    </a>
                  </Button>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
