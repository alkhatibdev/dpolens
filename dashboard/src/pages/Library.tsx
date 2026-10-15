import { ArrowUpRight, FileText } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import type { Document } from "@/api/client";
import { useDocuments } from "@/api/queries";
import { FilterButton } from "@/components/Filters";
import { Chip, Failed, Loading, Panel } from "@/components/States";
import { formatDate, languageName, nativeLanguageName } from "@/lib/format";

type Kind = "all" | "law" | "org_policy";

function DocumentCard({ document }: { document: Document }) {
  const { t } = useTranslation();
  const prevailing = document.languages.length > 1 ? document.authoritative_language : null;
  return (
    <Link
      to={`/library/${document.slug}`}
      className="flex flex-col gap-3.5 rounded-[20px] bg-white p-5 text-ink hover:shadow-[0_8px_24px_rgba(17,22,19,0.07)] sm:p-6"
    >
      <div className="flex items-start justify-between gap-3">
        {document.in_selected_laws ? (
          <Chip tone="soft">{t("library.selected")}</Chip>
        ) : (
          <Chip tone="quiet">{t("library.notSelected")}</Chip>
        )}
        <span className="grid size-10 shrink-0 place-items-center rounded-full border-[1.5px] border-ink">
          <ArrowUpRight aria-hidden className="size-4" />
        </span>
      </div>
      <div>
        <div className="text-sm text-muted">
          {[document.jurisdiction, document.kind === "law" ? t("library.law") : t("library.policy")]
            .filter(Boolean)
            .join(" · ")}
        </div>
        <h2 className="mt-1 text-[19px] leading-snug font-semibold sm:text-[21px]">
          {document.title}
        </h2>
      </div>
      <div className="flex flex-wrap gap-2">
        {document.languages.map((lang) =>
          lang === prevailing ? (
            <Chip key={lang} tone="brand" lang={lang}>
              {nativeLanguageName(lang)} · {t("library.prevails")}
            </Chip>
          ) : (
            <Chip key={lang} tone="quiet">
              {languageName(lang)}
              {prevailing ? `, ${t("library.officialTranslation")}` : ""}
            </Chip>
          ),
        )}
      </div>
      <dl className="mt-auto grid grid-cols-[0.8fr_1.5fr_0.9fr] gap-3 border-t border-line pt-3.5">
        <div>
          <dt className="text-xs text-muted">{t("library.clauses")}</dt>
          <dd className="text-[17px] font-semibold">{document.clauses}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted">{t("library.inForce")}</dt>
          <dd className="text-[17px] font-semibold">
            {formatDate(document.effective_date, "short")}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">{t("library.version")}</dt>
          <dd className="text-[17px] font-semibold">{document.version_label ?? "-"}</dd>
        </div>
      </dl>
    </Link>
  );
}

export function LibraryPage() {
  const { t } = useTranslation();
  const documents = useDocuments();
  const [kind, setKind] = useState<Kind>("all");
  const [language, setLanguage] = useState<string | null>(null);

  const all = documents.data?.documents ?? [];
  const languages = [...new Set(all.flatMap((document) => document.languages))].sort();
  const shown = all.filter(
    (document) =>
      (kind === "all" || document.kind === kind) &&
      (language === null || document.languages.includes(language)),
  );
  const count = (wanted: Kind) =>
    wanted === "all" ? all.length : all.filter((document) => document.kind === wanted).length;
  const noPolicies = count("org_policy") === 0;

  return (
    <Panel>
      <div>
        <h1 className="text-[32px] font-semibold tracking-[-0.025em] sm:text-[40px]">
          {t("library.title")}
        </h1>
        <p className="mt-1.5 text-[15px] text-muted sm:text-base">{t("library.subtitle")}</p>
      </div>

      <div role="group" aria-label={t("library.title")} className="flex flex-wrap gap-2">
        {(["all", "law", "org_policy"] as const).map((wanted) => (
          <FilterButton key={wanted} pressed={kind === wanted} onClick={() => setKind(wanted)}>
            {t(
              wanted === "all"
                ? "library.everything"
                : wanted === "law"
                  ? "library.laws"
                  : "library.policies",
            )}{" "}
            · {count(wanted)}
          </FilterButton>
        ))}
        {languages.length > 1 ? (
          <>
            <span aria-hidden className="mx-1 my-2 w-px bg-line-strong" />
            {languages.map((lang) => (
              <FilterButton
                key={lang}
                lang={lang}
                pressed={language === lang}
                onClick={() => setLanguage((now) => (now === lang ? null : lang))}
              >
                {nativeLanguageName(lang)}
              </FilterButton>
            ))}
          </>
        ) : null}
      </div>

      {documents.isPending ? <Loading /> : null}
      {documents.error ? <Failed onRetry={() => void documents.refetch()} /> : null}
      {documents.data ? (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(min(100%,340px),1fr))] gap-4">
          {shown.map((document) => (
            <DocumentCard key={document.slug} document={document} />
          ))}
          {noPolicies && kind !== "law" ? (
            <div className="flex min-h-[220px] flex-col justify-center gap-2.5 rounded-[20px] border-2 border-dashed border-line-strong p-6">
              <FileText aria-hidden className="size-9 text-brand-dark" />
              <h2 className="text-[19px] font-semibold">{t("library.policiesEmptyTitle")}</h2>
              <p className="text-[15px] leading-relaxed text-muted">
                {t("library.policiesEmptyBody")}
              </p>
            </div>
          ) : null}
          {shown.length === 0 && !(noPolicies && kind !== "law") ? (
            <p className="text-muted">{t("library.noneShown")}</p>
          ) : null}
        </div>
      ) : null}
    </Panel>
  );
}
