import { ChevronDown, Search } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import { ApiError, type SearchResult } from "@/api/client";
import { useDocuments, useSearch, type SearchOptions } from "@/api/queries";
import { CopyCitationButton } from "@/components/CopyCitation";
import { Notice } from "@/components/Notice";
import { Chip, Failed, Loading, Panel } from "@/components/States";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Switch } from "@/components/ui/switch";
import { namesOf, prevailingLanguage } from "@/lib/citation";
import { formatDate, isRightToLeft, languageName } from "@/lib/format";
import { SETTINGS_MANAGE } from "@/lib/permissions";
import { cn } from "@/lib/utils";
import { usePermitted } from "@/session";

const QUERY_LANGUAGES = ["en", "ar"] as const;

function optionsFrom(params: URLSearchParams): SearchOptions {
  return {
    query: params.get("q") ?? "",
    laws: (params.get("laws") ?? "").split(",").filter(Boolean),
    asOf: params.get("as_of"),
    lang: params.get("lang"),
    includeExplanatory: params.get("explanatory") === "1",
  };
}

function lawName(slug: string): string {
  return slug.toUpperCase();
}

function listOf(names: string[]): string {
  return new Intl.ListFormat("en-GB", { type: "conjunction" }).format(names);
}

function ResultCard({
  result,
  rank,
  results,
  query,
}: {
  result: SearchResult;
  rank: number;
  results: SearchResult[];
  query: string;
}) {
  const { t } = useTranslation();
  const { clause } = result;
  const prevails = prevailingLanguage(clause);
  const where = [clause.document_title, ...result.breadcrumb.map(namesOf)]
    .filter(Boolean)
    .join(" › ");

  return (
    <article className="grid grid-cols-[44px_minmax(0,1fr)] gap-x-3 rounded-[20px] bg-white p-4 sm:gap-x-4 sm:p-6">
      <span
        className={cn(
          "grid size-11 place-items-center rounded-[14px] text-[17px] font-semibold",
          rank === 1 ? "bg-brand text-white" : "bg-field",
        )}
      >
        {rank}
      </span>
      <div className="flex min-w-0 flex-col gap-2.5">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2">
          <div className="min-w-0">
            <div className="font-mono text-[13px] break-all text-brand-dark">{clause.key}</div>
            <h2 className="mt-1 text-base leading-snug font-semibold sm:text-[17px]">{where}</h2>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {prevails ? (
              <Chip tone="soft">
                {t("document.prevails", { language: languageName(prevails) })}
              </Chip>
            ) : null}
            {clause.version_label ? (
              <Chip tone="quiet">{t("document.version", { version: clause.version_label })}</Chip>
            ) : null}
          </div>
        </div>
        <p
          lang={clause.lang}
          dir={isRightToLeft(clause.lang) ? "rtl" : "ltr"}
          className="text-[15px] leading-relaxed sm:text-base"
        >
          {clause.label ? <span className="font-semibold">{clause.label} </span> : null}
          {clause.text}
        </p>
        {prevails && clause.authoritative_text ? (
          <p
            lang={prevails}
            dir={isRightToLeft(prevails) ? "rtl" : "ltr"}
            className="rounded-[14px] bg-panel px-4 py-3 text-base"
          >
            {clause.authoritative_text}
          </p>
        ) : null}
        <div className="mt-1 flex flex-wrap gap-2.5">
          <Button asChild variant="dark" size="sm">
            <Link to={`/clauses/${encodeURIComponent(clause.key)}`} state={{ results, query }}>
              {t("search.open")}
            </Link>
          </Button>
          <CopyCitationButton clause={clause} breadcrumb={result.breadcrumb} />
        </div>
      </div>
    </article>
  );
}

export function SearchPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const options = optionsFrom(params);
  const [draft, setDraft] = useState(options.query);
  const search = useSearch(options);
  const documents = useDocuments();
  const can = usePermitted();

  // The library lists the organisation's laws only, so these are the ones to choose from.
  const laws = [
    ...new Set(
      (documents.data?.documents ?? [])
        .map((document) => document.pack_slug)
        .filter((slug): slug is string => slug !== null),
    ),
  ].sort();
  const searched = search.data?.laws ?? options.laws;

  function update(
    changes: Partial<Record<"q" | "laws" | "as_of" | "lang" | "explanatory", string | null>>,
  ) {
    const next = new URLSearchParams(params);
    for (const [name, value] of Object.entries(changes)) {
      if (value === null || value === "") {
        next.delete(name);
      } else {
        next.set(name, value);
      }
    }
    setParams(next);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    update({ q: draft.trim() });
  }

  const results = search.data?.results ?? [];

  return (
    <Panel>
      <form role="search" onSubmit={submit} className="flex flex-wrap gap-2.5">
        <label className="flex h-[60px] min-w-0 flex-[1_1_420px] items-center gap-3 rounded-[18px] border-2 border-ink bg-white px-5">
          <Search aria-hidden className="size-5 shrink-0" />
          <span className="sr-only">{t("search.label")}</span>
          <input
            type="search"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder={t("search.placeholder")}
            dir="auto"
            className="min-w-0 flex-1 bg-transparent text-[17px] font-medium outline-none placeholder:font-normal placeholder:text-muted"
          />
        </label>
        <Button type="submit" className="h-[60px] rounded-[18px] px-7 text-base">
          {t("search.submit")}
        </Button>
      </form>

      <div className="flex flex-wrap items-center gap-2">
        {searched.length ? (
          <span className="me-1 text-sm text-ink-2">
            {t("search.scope", { laws: listOf(searched.map(lawName)) })}
          </span>
        ) : null}

        <DropdownMenu>
          <DropdownMenuTrigger className="inline-flex h-10 items-center gap-1.5 rounded-full border border-line-strong bg-white px-3.5 text-[13px] font-medium hover:bg-field">
            {options.laws.length ? listOf(options.laws.map(lawName)) : t("search.allLaws")}
            <ChevronDown aria-hidden className="size-4" />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start">
            <DropdownMenuItem onSelect={() => update({ laws: null })}>
              {t("search.allLaws")}
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            {laws.map((slug) => (
              <DropdownMenuItem key={slug} onSelect={() => update({ laws: slug })}>
                {lawName(slug)}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>

        <label className="inline-flex h-10 items-center gap-2 rounded-full border border-line-strong bg-white px-3.5 text-[13px] font-medium">
          <span>
            {options.asOf
              ? t("search.inForceOn", { date: formatDate(options.asOf) })
              : t("search.inForceToday")}
          </span>
          <input
            type="date"
            value={options.asOf ?? ""}
            onChange={(event) => update({ as_of: event.target.value || null })}
            aria-label={t("search.inForceToday")}
            className="w-[22px] cursor-pointer bg-transparent text-transparent [&::-webkit-calendar-picker-indicator]:cursor-pointer"
          />
        </label>

        <DropdownMenu>
          <DropdownMenuTrigger className="inline-flex h-10 items-center gap-1.5 rounded-full border border-line-strong bg-white px-3.5 text-[13px] font-medium hover:bg-field">
            {options.lang
              ? t("search.askedIn", { language: languageName(options.lang) })
              : t("search.detected")}
            <ChevronDown aria-hidden className="size-4" />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start">
            <DropdownMenuLabel className="text-xs text-muted">
              {t("search.label")}
            </DropdownMenuLabel>
            <DropdownMenuItem onSelect={() => update({ lang: null })}>
              {t("search.detected")}
            </DropdownMenuItem>
            {QUERY_LANGUAGES.map((lang) => (
              <DropdownMenuItem key={lang} onSelect={() => update({ lang })}>
                {t("search.askedIn", { language: languageName(lang) })}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>

        <label className="inline-flex h-10 cursor-pointer items-center gap-2 rounded-full border border-line-strong bg-white ps-2.5 pe-3.5 text-[13px] font-medium">
          <Switch
            checked={options.includeExplanatory}
            onCheckedChange={(checked) => update({ explanatory: checked ? "1" : null })}
          />
          {t("search.includeExplanatory")}
        </label>
      </div>

      {!options.query ? <p className="text-muted">{t("search.prompt")}</p> : null}
      {options.query && search.isPending ? <Loading /> : null}
      {search.error instanceof ApiError && search.error.status === 409 ? (
        <Notice tone="warn">
          {t("search.noLaws")}{" "}
          {can.has(SETTINGS_MANAGE) ? (
            <Link to="/laws" className="font-medium text-brand-dark underline underline-offset-2">
              {t("search.chooseLaws")}
            </Link>
          ) : (
            t("search.askAdministrator")
          )}
        </Notice>
      ) : search.error ? (
        <Failed onRetry={() => void search.refetch()} />
      ) : null}
      {search.data ? (
        <>
          <p className="text-sm text-muted" aria-live="polite">
            {results.length ? t("search.results", { count: results.length }) : t("search.none")}
          </p>
          <div className={cn("flex flex-col gap-4", search.isPlaceholderData && "opacity-60")}>
            {results.map((result, index) => (
              <ResultCard
                key={result.clause.key}
                result={result}
                rank={index + 1}
                results={results}
                query={options.query}
              />
            ))}
          </div>
        </>
      ) : null}
    </Panel>
  );
}
