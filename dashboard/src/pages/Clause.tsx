import { History } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link, useLocation, useParams, useSearchParams } from "react-router";

import { ApiError, type Clause, type SearchResult } from "@/api/client";
import { CitedThisWeek } from "@/components/CitedThisWeek";
import { usePolicyVersions } from "@/api/policies";
import { useClause, useSubtrees } from "@/api/queries";
import { CopyCitationButton } from "@/components/CopyCitation";
import { Notice } from "@/components/Notice";
import { Reading } from "@/components/Reading";
import { Chip, Failed, Loading, Missing, Panel } from "@/components/States";
import { Button } from "@/components/ui/button";
import { namesOf, prevailingLanguage } from "@/lib/citation";
import { formatDate, isRightToLeft, languageName, readingOrder } from "@/lib/format";
import { isolate } from "@/lib/policies";

interface FromSearch {
  query?: string;
  results?: SearchResult[];
}

/** The fields the MCP server hands an assistant for this clause, under its own names. */
function assistantView(clause: Clause): string {
  const fields: [string, string][] = [
    ["key", clause.key],
    ["lang", clause.lang],
    ["authoritative", String(clause.is_authoritative)],
    ["prevails", prevailingLanguage(clause) ?? "null"],
    ["version", clause.version_label ?? "null"],
    ["in_force_since", clause.effective_date],
    ["trust_tier", clause.trust_tier ?? "null"],
    ["obliges", String(clause.is_normative)],
  ];
  return fields.map(([name, value]) => `${name}: ${value}`).join("\n");
}

/** What the clause sits in, outermost first, named in its own language. */
function Title({ trail, lang }: { trail: readonly Clause[]; lang: string }) {
  const article = trail[0];
  const heading = [...trail].reverse().find((clause) => clause.heading)?.heading;
  const title = heading ?? (article ? namesOf(article) : "");
  if (!title) {
    return null;
  }
  return (
    <div lang={lang} dir={isRightToLeft(lang) ? "rtl" : "ltr"}>
      {article?.label ? <div className="text-sm text-muted">{article.label}</div> : null}
      <h1 className="mt-1 text-[26px] leading-tight font-semibold tracking-[-0.025em] sm:text-[34px]">
        {title}
      </h1>
    </div>
  );
}

/** A key without its document's slug, as a reader of that document names the clause. */
function own(key: string, slug: string): string {
  return isolate(key.startsWith(`${slug}:`) ? key.slice(slug.length + 1) : key);
}

/** Reading a policy's clause in a version no longer in force: when that was, and where the rule is now. */
function OldVersion({
  clause,
  now,
  until,
}: {
  clause: Clause;
  now: NonNullable<Detail["now"]>;
  until: string | null;
}) {
  const { t } = useTranslation();
  const slug = clause.document_slug;
  const label = isolate(clause.version_label ?? "");
  const facts = {
    label: isolate(now.version_label ?? ""),
    date: formatDate(now.effective_date),
    key: now.key ? own(now.key, slug) : "",
  };
  let where: string;
  if (now.key === null) {
    where = t("clause.nowRemoved", facts);
  } else if (now.moved) {
    where = now.changed ? t("clause.nowMovedChanged", facts) : t("clause.nowMoved", facts);
  } else {
    where = now.changed ? t("clause.nowChanged", facts) : t("clause.nowSame", facts);
  }
  return (
    <div
      role="note"
      className="flex flex-wrap items-center gap-3.5 rounded-[20px] bg-brand-soft px-5 py-[18px]"
    >
      <History aria-hidden className="size-[22px] shrink-0 text-brand-dark" />
      <div className="min-w-0 flex-[1_1_460px]">
        <p className="text-base font-semibold text-brand-dark">
          {until
            ? t("clause.readingOld", {
                label,
                from: formatDate(clause.effective_date),
                until: formatDate(until),
              })
            : t("clause.readingOldFrom", { label, from: formatDate(clause.effective_date) })}
        </p>
        <p className="mt-1 text-[15px] leading-normal">{where}</p>
      </div>
      {now.key ? (
        <Button asChild size="sm">
          <Link to={`/clauses/${encodeURIComponent(now.key)}`}>
            {t("clause.readNow", { key: own(now.key, slug) })}
          </Link>
        </Button>
      ) : null}
    </div>
  );
}

/** The key read today names another rule: what it names now, and where the old one went. */
function SameKeyToday({ today }: { today: Detail }) {
  const { t } = useTranslation();
  const clause = today.clause;
  const slug = clause.document_slug;
  const formerly = today.formerly;
  return (
    <section className="flex flex-col gap-2.5 rounded-[20px] bg-white p-5 sm:p-6">
      <h2 className="text-[19px] font-semibold">{t("clause.sameKeyToday")}</h2>
      <div className="flex flex-wrap items-center gap-2">
        <Link
          to={`/clauses/${encodeURIComponent(clause.key)}`}
          className="font-mono text-[13px] font-medium text-brand-dark hover:underline"
        >
          {clause.key}
        </Link>
        {clause.version_label ? (
          <Chip>{t("document.version", { version: clause.version_label })}</Chip>
        ) : null}
      </div>
      <p dir="auto" className="text-[15px] leading-relaxed">
        {clause.heading ?? clause.text}
      </p>
      {formerly ? (
        <div className="rounded-[14px] bg-field px-3.5 py-3 text-sm leading-normal text-ink-2">
          {formerly.now
            ? t("clause.formerly", {
                label: isolate(formerly.version_label ?? ""),
                key: clause.key,
                now: own(formerly.now, slug),
              })
            : t("clause.formerlyRemoved", {
                label: isolate(formerly.version_label ?? ""),
                key: clause.key,
              })}{" "}
          <em dir="auto">{formerly.heading ?? formerly.text}</em>
        </div>
      ) : null}
    </section>
  );
}

type Detail = NonNullable<ReturnType<typeof useClause>["data"]>;

export function ClausePage() {
  const { t, i18n } = useTranslation();
  const { key = "" } = useParams();
  const [params] = useSearchParams();
  const asOf = params.get("as_of");
  const state = (useLocation().state as FromSearch | null) ?? {};
  const detail = useClause(key, i18n.language, true, asOf);

  const clause = detail.data?.clause;
  const languages = clause
    ? [
        ...new Set(
          [clause.lang, clause.authoritative_language].filter(
            (lang): lang is string => typeof lang === "string",
          ),
        ),
      ]
    : [];
  const other = languages.find((lang) => lang !== clause?.lang);
  const otherDetail = useClause(key, other, other !== undefined, asOf);
  const reading = useSubtrees(clause ? key : null, languages, asOf);
  const now = detail.data?.now ?? null;
  const versions = usePolicyVersions(clause?.document_slug ?? "", now !== null);
  // The rule moved away from this key, so today the key may name another one.
  const today = useClause(key, i18n.language, now !== null && now.key !== key);

  if (detail.isPending) {
    return <Loading />;
  }
  if (detail.error instanceof ApiError && detail.error.status === 404) {
    return <Missing />;
  }
  if (!detail.data || !clause) {
    return <Failed onRetry={() => void detail.refetch()} />;
  }

  const breadcrumb = detail.data.breadcrumb;
  const article = breadcrumb[0] ?? clause;
  const until =
    versions.data?.versions.find(
      (entry) => entry.state !== "draft" && entry.effective_date === clause.effective_date,
    )?.until ?? null;
  const prevails = prevailingLanguage(clause);
  const related = (state.results ?? []).filter((result) => result.clause.key !== key).slice(0, 3);

  return (
    <Panel>
      <div className="text-sm text-muted">
        <Link to={`/library/${clause.document_slug}`} className="hover:text-ink">
          {clause.document_title}
        </Link>
      </div>
      {now ? <OldVersion clause={clause} now={now} until={until} /> : null}
      {clause.archived ? (
        <Notice tone="quiet">{t("clause.archived", { title: clause.document_title })}</Notice>
      ) : null}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <Title trail={breadcrumb} lang={clause.lang} />
        {other && otherDetail.data ? (
          <Title trail={otherDetail.data.breadcrumb} lang={other} />
        ) : null}
      </div>
      <div className="flex flex-wrap gap-2">
        {clause.version_label ? (
          <Chip>{t("document.version", { version: clause.version_label })}</Chip>
        ) : null}
        <Chip>{t("document.inForce", { date: formatDate(clause.effective_date) })}</Chip>
        {clause.trust_tier === "verified" || clause.trust_tier === "community" ? (
          <Chip>{t(`document.trust.${clause.trust_tier}`)}</Chip>
        ) : null}
        {prevails ? (
          <Chip tone="brand">{t("document.prevails", { language: languageName(prevails) })}</Chip>
        ) : null}
      </div>

      <div className="flex flex-col gap-4 xl:flex-row xl:items-start">
        <article className="min-w-0 flex-[2] rounded-[20px] bg-white px-4 pt-2 pb-2 sm:px-6">
          {reading.isPending ? <Loading /> : null}
          {reading.error ? <Failed onRetry={reading.refetch} /> : null}
          {!reading.isPending && !reading.error ? (
            <Reading
              byLanguage={reading.byLanguage}
              languages={readingOrder(languages)}
              breadcrumb={breadcrumb}
            />
          ) : null}
        </article>

        <div className="flex min-w-0 flex-1 flex-col gap-4 xl:max-w-[400px]">
          {today.data ? <SameKeyToday today={today.data} /> : null}
          <CitedThisWeek clauseKey={clause.key} />
          <section className="flex flex-col gap-3.5 rounded-[20px] bg-ink p-5 text-white sm:p-6">
            <h2 className="text-[19px] font-semibold">{t("clause.assistant")}</h2>
            <pre className="overflow-x-auto rounded-xl bg-[#222924] p-3.5 font-mono text-xs leading-7 whitespace-pre-wrap text-[#e4e9e5]">
              {assistantView(clause)}
            </pre>
            <CopyCitationButton clause={clause} breadcrumb={breadcrumb} variant="primary" />
            <Button asChild variant="ghost" size="sm" className="text-white hover:bg-white/10">
              <Link
                to={`/library/${clause.document_slug}?part=${encodeURIComponent(article.key)}${asOf ? `&as_of=${asOf}` : ""}#${encodeURIComponent(clause.key)}`}
              >
                {t("clause.readArticle")}
              </Link>
            </Button>
          </section>

          {related.length ? (
            <section className="flex flex-col gap-3 rounded-[20px] bg-white p-5 sm:p-6">
              <h2 className="text-[19px] font-semibold">{t("clause.alsoAnswers")}</h2>
              {related.map((result) => (
                <Link
                  key={result.clause.key}
                  to={`/clauses/${encodeURIComponent(result.clause.key)}`}
                  state={state}
                  className="block rounded-[14px] bg-panel px-4 py-3.5 hover:bg-field"
                >
                  <div className="font-mono text-xs text-brand-dark">{result.clause.key}</div>
                  <div className="mt-1 text-[15px] font-semibold">
                    {[result.clause.document_title, ...result.breadcrumb.map(namesOf)]
                      .filter(Boolean)
                      .slice(-2)
                      .join(" · ")}
                  </div>
                  <p className="mt-1 line-clamp-3 text-sm leading-relaxed text-ink-2">
                    {result.clause.text}
                  </p>
                </Link>
              ))}
            </section>
          ) : null}
        </div>
      </div>
    </Panel>
  );
}
