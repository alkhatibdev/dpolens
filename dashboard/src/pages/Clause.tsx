import { useTranslation } from "react-i18next";
import { Link, useLocation, useParams } from "react-router";

import { ApiError, type Clause, type SearchResult } from "@/api/client";
import { CitedThisWeek } from "@/components/CitedThisWeek";
import { useClause, useSubtrees } from "@/api/queries";
import { CopyCitationButton } from "@/components/CopyCitation";
import { Reading } from "@/components/Reading";
import { Chip, Failed, Loading, Missing, Panel } from "@/components/States";
import { Button } from "@/components/ui/button";
import { namesOf, prevailingLanguage } from "@/lib/citation";
import { formatDate, isRightToLeft, languageName, readingOrder } from "@/lib/format";

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

export function ClausePage() {
  const { t, i18n } = useTranslation();
  const { key = "" } = useParams();
  const state = (useLocation().state as FromSearch | null) ?? {};
  const detail = useClause(key, i18n.language);

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
  const otherDetail = useClause(key, other, other !== undefined);
  const reading = useSubtrees(clause ? key : null, languages);

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
  const prevails = prevailingLanguage(clause);
  const related = (state.results ?? []).filter((result) => result.clause.key !== key).slice(0, 3);

  return (
    <Panel>
      <div className="text-sm text-muted">
        <Link to={`/library/${clause.document_slug}`} className="hover:text-ink">
          {clause.document_title}
        </Link>
      </div>
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
          <CitedThisWeek clauseKey={clause.key} />
          <section className="flex flex-col gap-3.5 rounded-[20px] bg-ink p-5 text-white sm:p-6">
            <h2 className="text-[19px] font-semibold">{t("clause.assistant")}</h2>
            <pre className="overflow-x-auto rounded-xl bg-[#222924] p-3.5 font-mono text-xs leading-7 whitespace-pre-wrap text-[#e4e9e5]">
              {assistantView(clause)}
            </pre>
            <CopyCitationButton clause={clause} breadcrumb={breadcrumb} variant="primary" />
            <Button asChild variant="ghost" size="sm" className="text-white hover:bg-white/10">
              <Link
                to={`/library/${clause.document_slug}?part=${encodeURIComponent(article.key)}#${encodeURIComponent(clause.key)}`}
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
