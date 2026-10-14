import { ArrowUpRight, ChevronDown } from "lucide-react";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Link, useLocation, useParams, useSearchParams } from "react-router";

import { ApiError, type Clause, type OutlineEntry } from "@/api/client";
import { useDocument, useSubtrees } from "@/api/queries";
import { Reading } from "@/components/Reading";
import { Chip, Failed, Loading, Missing, Panel } from "@/components/States";
import { formatDate, isRightToLeft, languageName, readingOrder } from "@/lib/format";
import { cn } from "@/lib/utils";

interface Section {
  key: string;
  label: string;
  points: number;
}

/** The paragraphs directly beneath the clause being read, and how many points each holds. */
function sectionsOf(clauses: readonly Clause[]): Section[] {
  const root = clauses[0];
  if (!root) {
    return [];
  }
  const sections: Section[] = [];
  for (const clause of clauses.slice(1)) {
    if (clause.depth === root.depth + 1) {
      sections.push({ key: clause.key, label: clause.label ?? clause.key, points: 0 });
    } else {
      const last = sections[sections.length - 1];
      if (last && clause.depth === root.depth + 2) {
        last.points += 1;
      }
    }
  }
  return sections;
}

function Contents({
  outline,
  current,
  sections,
  slug,
}: {
  outline: readonly OutlineEntry[];
  current: string | null;
  sections: readonly Section[];
  slug: string;
}) {
  const { t } = useTranslation();
  return (
    <ol className="flex flex-col gap-0.5 text-sm">
      {outline.map((entry) => {
        const open = entry.key === current;
        return (
          <li key={entry.key}>
            <Link
              to={`/library/${slug}?part=${encodeURIComponent(entry.key)}`}
              aria-current={open ? "true" : undefined}
              className={cn(
                "flex items-baseline gap-2.5 rounded-[10px] px-2 py-2.5 text-ink-2 hover:bg-field",
                open && "bg-brand-soft font-semibold text-brand-dark hover:bg-brand-soft",
              )}
            >
              <span className="w-12 shrink-0 font-semibold text-muted">
                {entry.label?.replace(/^(Article|Recital)\s*/i, "") ?? ""}
              </span>
              <span>{entry.heading ?? entry.label ?? entry.key}</span>
            </Link>
            {open && sections.length ? (
              <ol className="ms-14 mt-1 mb-1.5 flex flex-col gap-0.5">
                {sections.map((section) => (
                  <li key={section.key}>
                    <a
                      href={`#${section.key}`}
                      className="block rounded-lg px-2 py-1.5 text-[13px] text-ink-2 hover:bg-field"
                    >
                      {section.label}
                      {section.points
                        ? ` · ${t("document.points", { count: section.points })}`
                        : ""}
                    </a>
                  </li>
                ))}
              </ol>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}

function Heading({ byLanguage, order }: { byLanguage: Record<string, Clause[]>; order: string[] }) {
  return (
    <div
      className={cn(
        "flex flex-col gap-3 border-b-2 border-ink pb-4 md:grid md:items-end md:gap-x-[18px]",
        order.length > 1 ? "md:grid-cols-[minmax(0,1fr)_76px_minmax(0,1fr)]" : "md:grid-cols-1",
      )}
    >
      {order.map((lang, index) => {
        const root = byLanguage[lang]?.[0];
        if (!root) {
          return null;
        }
        return (
          <h2
            key={lang}
            lang={lang}
            dir={isRightToLeft(lang) ? "rtl" : "ltr"}
            className={cn(
              "text-[22px] leading-tight font-semibold tracking-[-0.02em] sm:text-[26px]",
              index === 1 && "md:col-start-3",
            )}
          >
            {root.label}
            {root.heading ? (
              <>
                <br />
                {root.heading}
              </>
            ) : null}
          </h2>
        );
      })}
    </div>
  );
}

export function DocumentPage() {
  const { t, i18n } = useTranslation();
  const { slug = "" } = useParams();
  const [params] = useSearchParams();
  const { hash } = useLocation();
  const document = useDocument(slug, i18n.language);

  const detail = document.data;
  const outline = detail?.outline ?? [];
  const part = params.get("part") ?? outline[0]?.key ?? null;
  const languages = detail?.document.languages ?? [];
  const reading = useSubtrees(detail ? part : null, languages);
  const order = readingOrder(languages);

  useEffect(() => {
    if (hash && !reading.isPending) {
      globalThis.document.getElementById(decodeURIComponent(hash.slice(1)))?.scrollIntoView();
    }
  }, [hash, reading.isPending]);

  if (document.isPending) {
    return <Loading />;
  }
  if (document.error instanceof ApiError && document.error.status === 404) {
    return <Missing />;
  }
  if (!detail) {
    return <Failed onRetry={() => void document.refetch()} />;
  }

  const summary = detail.document;
  const prevailing = languages.length > 1 ? summary.authoritative_language : null;
  const currentEntry = outline.find((entry) => entry.key === part);
  const sections = sectionsOf(reading.byLanguage[order[0] ?? ""] ?? []);

  return (
    <Panel>
      <div className="text-sm text-muted">
        <Link to="/library" className="hover:text-ink">
          {t("library.title")}
        </Link>
        {summary.jurisdiction ? (
          <>
            <span aria-hidden> › </span>
            {summary.jurisdiction}
          </>
        ) : null}
      </div>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <h1 className="max-w-[760px] text-[26px] leading-tight font-semibold tracking-[-0.025em] sm:text-[34px]">
          {summary.title}
        </h1>
        {summary.source_url ? (
          <a
            href={summary.source_url}
            target="_blank"
            rel="noreferrer noopener"
            className="inline-flex h-11 items-center gap-2 rounded-[14px] border-[1.5px] border-brand-dark px-4 text-[15px] font-semibold text-brand-dark hover:bg-brand-soft"
          >
            {t("document.openSource")}
            <ArrowUpRight aria-hidden className="size-4" />
          </a>
        ) : null}
      </div>
      <div className="flex flex-wrap gap-2">
        {summary.version_label ? (
          <Chip>{t("document.version", { version: summary.version_label })}</Chip>
        ) : null}
        <Chip>{t("document.inForce", { date: formatDate(summary.effective_date) })}</Chip>
        <Chip>{t("document.clauses", { count: summary.clauses })}</Chip>
        {summary.trust_tier === "verified" || summary.trust_tier === "community" ? (
          <Chip>{t(`document.trust.${summary.trust_tier}`)}</Chip>
        ) : null}
        {prevailing ? (
          <Chip tone="brand">{t("document.prevails", { language: languageName(prevailing) })}</Chip>
        ) : null}
      </div>

      <div className="flex flex-col gap-4 lg:flex-row lg:items-start">
        <details className="group rounded-[20px] bg-white lg:hidden">
          <summary className="flex min-h-14 cursor-pointer list-none items-center justify-between gap-3 px-5 font-semibold">
            <span>
              {t("document.contents")}
              {currentEntry ? (
                <span className="font-normal text-muted"> · {currentEntry.label}</span>
              ) : null}
            </span>
            <ChevronDown
              aria-hidden
              className="size-5 transition-transform group-open:rotate-180"
            />
          </summary>
          <div className="max-h-[60vh] overflow-y-auto px-3 pb-3">
            <Contents outline={outline} current={part} sections={sections} slug={slug} />
          </div>
        </details>

        <section
          aria-label={t("document.contents")}
          className="hidden w-[320px] shrink-0 rounded-[20px] bg-white px-3 py-4 lg:sticky lg:top-4 lg:block lg:max-h-[calc(100dvh-2rem)] lg:overflow-y-auto"
        >
          <h2 className="px-2 pb-2.5 text-[17px] font-semibold">{t("document.contents")}</h2>
          <Contents outline={outline} current={part} sections={sections} slug={slug} />
        </section>

        <article className="min-w-0 flex-1 rounded-[20px] bg-white px-4 pt-5 pb-2 sm:px-6 sm:pt-6">
          {reading.isPending ? <Loading /> : null}
          {reading.error ? <Failed onRetry={reading.refetch} /> : null}
          {!reading.isPending && !reading.error ? (
            <>
              <Heading byLanguage={reading.byLanguage} order={order} />
              <Reading byLanguage={reading.byLanguage} languages={languages} breadcrumb={[]} />
            </>
          ) : null}
        </article>
      </div>
    </Panel>
  );
}
