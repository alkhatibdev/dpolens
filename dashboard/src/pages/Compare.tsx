import { ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link, useParams, useSearchParams } from "react-router";

import { ApiError } from "@/api/client";
import { useComparison, usePolicyVersions, type ComparedClause } from "@/api/policies";
import { Notice } from "@/components/Notice";
import { PillSelect } from "@/components/PillSelect";
import { ChangeRow, Stat, Words } from "@/components/policies/WhatChanged";
import { Chip, Failed, Loading, Missing, Panel } from "@/components/States";
import { formatDate } from "@/lib/format";
import { isolate, shortKey } from "@/lib/policies";

/** What happened to a clause, in the chip its row carries. */
function ChangeChip({ clause, slug }: { clause: ComparedClause; slug: string }) {
  const { t } = useTranslation();
  const earlier = clause.earlier;
  if (clause.change === "added") {
    return <Chip tone="soft">{t("compare.new")}</Chip>;
  }
  if (clause.change === "moved" && earlier) {
    const key = isolate(shortKey(earlier.key, slug));
    const same = earlier.text === clause.text && earlier.heading === clause.heading;
    return (
      <Chip tone="soft">
        {same ? t("compare.moved", { key }) : t("compare.movedReworded", { key })}
      </Chip>
    );
  }
  return <Chip tone="soft">{t("compare.modified")}</Chip>;
}

/**
 * Any two published versions of a policy, clause by clause: what was reworded,
 * renumbered, added and removed, with the words that changed marked.
 */
export function ComparePage() {
  const { t } = useTranslation();
  const { slug = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const versions = usePolicyVersions(slug);
  const published = (versions.data?.versions ?? []).filter((entry) => entry.state !== "draft");
  // By default, the version in force against the one before it, or else the one after it.
  const inForce = published.find((entry) => entry.state === "in_force") ?? published[0];
  const at = inForce ? published.indexOf(inForce) : -1;
  const older = published[at + 1];
  const newer = at > 0 ? published[at - 1] : undefined;
  const [first, second] = older ? [older, inForce] : [inForce, newer];
  const from = Number(params.get("from")) || (second ? (first?.number ?? null) : null);
  const to = Number(params.get("to")) || (second?.number ?? null);
  const comparison = useComparison(slug, from, to);

  if (versions.isPending) {
    return <Loading />;
  }
  if (versions.error instanceof ApiError && versions.error.status === 404) {
    return <Missing />;
  }
  if (!versions.data) {
    return <Failed onRetry={() => void versions.refetch()} />;
  }

  const title = versions.data.title;
  const options = published.map((entry) => ({
    value: String(entry.number),
    label: t("compare.option", {
      label: isolate(entry.label),
      date: formatDate(entry.effective_date),
    }),
  }));
  const choose = (which: "from" | "to") => (value: string) => {
    const next = new URLSearchParams(params);
    next.set("from", String(from ?? ""));
    next.set("to", String(to ?? ""));
    next.set(which, value);
    setParams(next, { replace: true });
  };
  const found = comparison.data;
  const changed = found?.clauses.filter((clause) => clause.change !== "unchanged") ?? [];
  const same = found?.clauses.filter((clause) => clause.change === "unchanged") ?? [];
  const changes = found?.changes ?? {};
  const fresh = (changes.added ?? 0) + (changes.moved ?? 0);

  return (
    <Panel>
      <nav aria-label={t("review.crumbs")} className="flex flex-wrap gap-1.5 text-sm text-muted">
        <Link to="/library" className="hover:underline">
          {t("library.title")}
        </Link>
        <span aria-hidden>›</span>
        <Link to={`/library/${encodeURIComponent(slug)}`} className="hover:underline">
          <bdi>{title}</bdi>
        </Link>
        <span aria-hidden>›</span>
        <span className="text-ink-2">{t("compare.title")}</span>
      </nav>
      <h1 className="text-[32px] leading-tight font-semibold tracking-[-0.025em] sm:text-4xl">
        {t("compare.title")}
      </h1>

      {published.length < 2 ? (
        <Notice tone="quiet">{t("compare.onlyOne")}</Notice>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2.5">
            <PillSelect
              label={t("compare.from")}
              value={String(from ?? "")}
              options={options}
              onChange={choose("from")}
            />
            <ChevronRight aria-hidden className="size-[18px] text-muted" />
            <PillSelect
              label={t("compare.to")}
              value={String(to ?? "")}
              options={options}
              onChange={choose("to")}
            />
          </div>

          {comparison.error ? <Failed onRetry={() => void comparison.refetch()} /> : null}
          {from === to ? <Notice tone="quiet">{t("compare.identical")}</Notice> : null}
          {found && from !== to ? (
            <>
              <section className="flex flex-wrap gap-[18px] rounded-[20px] bg-white px-[22px] py-[18px]">
                <Stat
                  label={t("compare.reworded")}
                  value={changes.modified || t("compare.none")}
                  note={changes.modified ? t("compare.rewordedNote") : ""}
                />
                <Stat
                  label={t("compare.removed")}
                  value={changes.removed || t("compare.none")}
                  note={
                    changes.removed
                      ? t("compare.removedNote", { label: isolate(found.later.label) })
                      : ""
                  }
                />
                <Stat label={t("compare.added")} value={fresh || t("compare.none")} note="" />
                <Stat
                  label={t("compare.same")}
                  value={changes.unchanged || t("compare.none")}
                  note={changes.unchanged ? t("compare.sameNote") : ""}
                />
              </section>

              <section className="rounded-[20px] bg-white px-[22px] pt-1.5 pb-3">
                {changed.length === 0 && found.removed.length === 0 ? (
                  <p className="py-4 text-[15px] text-ink-2">{t("compare.identical")}</p>
                ) : null}
                {changed.map((clause) => (
                  <ChangeRow
                    key={clause.key}
                    keyText={shortKey(clause.key, slug)}
                    chips={<ChangeChip clause={clause} slug={slug} />}
                  >
                    <Words clause={clause} />
                  </ChangeRow>
                ))}
                {found.removed.map((gone) => (
                  <ChangeRow
                    key={`removed-${gone.key}`}
                    keyText={shortKey(gone.key, slug)}
                    keyNote={t("changes.inVersion", { label: isolate(found.earlier.label) })}
                    chips={
                      <span className="rounded-full bg-danger-soft px-3 py-1.5 text-[13px] font-semibold text-danger-ink">
                        {t("compare.removed")}
                      </span>
                    }
                  >
                    <p dir="auto" className="text-[15px] leading-relaxed text-muted line-through">
                      {gone.heading ?? gone.text}
                    </p>
                    <p className="text-[13px] text-muted">
                      {t("compare.removedCitation", {
                        label: isolate(found.earlier.label),
                        key: isolate(shortKey(gone.key, slug)),
                      })}
                    </p>
                  </ChangeRow>
                ))}
                {same.length ? (
                  <details className="px-1 pt-4 pb-1.5">
                    <summary className="cursor-pointer text-[15px] font-semibold">
                      {t("compare.sameFolded", { count: same.length })}
                    </summary>
                    <p className="mt-2 text-sm text-muted">
                      {same
                        .map((clause) =>
                          [shortKey(clause.key, slug), clause.heading].filter(Boolean).join(" "),
                        )
                        .join(", ")}
                    </p>
                  </details>
                ) : null}
              </section>
            </>
          ) : null}
          {comparison.isFetching && !found ? <Loading /> : null}
          <p className="text-sm leading-normal text-muted">{t("compare.note")}</p>
        </>
      )}
    </Panel>
  );
}
