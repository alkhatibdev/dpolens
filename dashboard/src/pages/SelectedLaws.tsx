import { Scale } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Navigate } from "react-router";

import type { Laws } from "@/api/client";
import { useChooseLaws, useLaws, useSearchEveryLaw } from "@/api/laws";
import { LawChoice } from "@/components/LawChoice";
import { Notice } from "@/components/Notice";
import { PageHeading } from "@/components/Page";
import { Failed, Loading, Panel } from "@/components/States";
import { Button } from "@/components/ui/button";
import { sourceName } from "@/lib/clauseName";
import { formatList, formatWhen } from "@/lib/format";
import { SETTINGS_MANAGE } from "@/lib/permissions";
import { usePermitted } from "@/session";

/** "GDPR and UAE PDPL": laws as a citation names them. */
function named(slugs: readonly string[]): string {
  return formatList(slugs.map((slug) => sourceName(slug, slug)));
}

/** What searches cover now, and who last decided it. */
function Coverage({ laws }: { laws: Laws }) {
  const { t } = useTranslation();
  const changed = laws.changed;
  let title: string;
  if (laws.selected) {
    title = t("laws.cover", { laws: named(laws.selected) });
  } else {
    title = changed ? t("laws.coverEvery") : t("laws.coverUntil");
  }
  let who = "";
  if (changed) {
    const when = formatWhen(changed.at);
    if (changed.by) {
      who = t(changed.cleared ? "laws.clearedBy" : "laws.chosenBy", { name: changed.by, when });
    } else {
      who = t(changed.cleared ? "laws.clearedOnCli" : "laws.chosenOnCli", { when });
    }
  }
  return (
    <section className="flex flex-wrap items-center gap-4 rounded-[20px] bg-white px-5 py-[18px]">
      <span
        aria-hidden
        className="grid size-10 shrink-0 place-items-center rounded-full bg-brand-soft text-brand-dark"
      >
        <Scale className="size-5" />
      </span>
      <div className="min-w-0 flex-[1_1_320px]">
        <h2 className="text-base font-semibold">{title}</h2>
        <p className="mt-0.5 text-sm text-muted">
          {who ? `${who} ` : ""}
          {t("laws.recorded")}
        </p>
      </div>
    </section>
  );
}

export function SelectedLawsPage() {
  const { t } = useTranslation();
  const can = usePermitted();
  const permitted = can.has(SETTINGS_MANAGE);
  const laws = useLaws(permitted);
  const choose = useChooseLaws();
  const every = useSearchEveryLaw();
  // The boxes ticked since the page was read, or null while nothing has changed.
  const [draft, setDraft] = useState<Set<string> | null>(null);

  if (!permitted) {
    return <Navigate to="/" replace />;
  }
  if (laws.isPending) {
    return <Loading />;
  }
  if (!laws.data) {
    return <Failed onRetry={() => void laws.refetch()} />;
  }

  const current = laws.data;
  const start = new Set(current.laws.filter((law) => law.searched).map((law) => law.slug));
  const shown = draft ?? start;
  const order = current.laws.map((law) => law.slug);
  const added = order.filter((slug) => shown.has(slug) && !start.has(slug));
  const removed = order.filter((slug) => start.has(slug) && !shown.has(slug));
  const busy = choose.isPending || every.isPending;

  function toggle(slug: string, on: boolean) {
    const next = new Set(shown);
    if (on) {
      next.add(slug);
    } else {
      next.delete(slug);
    }
    const unchanged = next.size === start.size && [...next].every((item) => start.has(item));
    setDraft(unchanged ? null : next);
  }

  function discard() {
    setDraft(null);
    choose.reset();
  }

  const summary = [
    added.length ? t("laws.adds", { laws: named(added) }) : "",
    removed.length ? t("laws.removes", { laws: named(removed) }) : "",
    shown.size
      ? t("laws.appliesNow")
      : t(current.selected ? "laws.noneTicked" : "laws.noneTickedYet"),
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <Panel>
      <PageHeading title={t("laws.title")} subtitle={t("laws.subtitle")} />
      <Coverage laws={current} />

      <fieldset className="min-w-0">
        <legend className="mb-3.5 text-xl font-semibold">{t("laws.loaded")}</legend>
        {current.laws.length ? (
          <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,340px),1fr))] gap-4">
            {current.laws.map((law) => (
              <LawChoice
                key={law.slug}
                law={law}
                checked={shown.has(law.slug)}
                disabled={busy}
                onChange={(on) => toggle(law.slug, on)}
              />
            ))}
          </div>
        ) : (
          <p className="text-muted">{t("laws.noneLoaded")}</p>
        )}
      </fieldset>

      {current.selected ? (
        <section className="flex flex-wrap items-center gap-4 rounded-[20px] bg-white p-5 sm:p-6">
          <div className="min-w-0 flex-[1_1_360px]">
            <h2 className="text-lg font-semibold">{t("laws.everyTitle")}</h2>
            <p className="mt-1.5 text-sm leading-relaxed text-muted">{t("laws.everyBody")}</p>
          </div>
          <Button
            variant="quiet"
            size="sm"
            disabled={busy}
            onClick={() => every.mutate(undefined, { onSuccess: () => setDraft(null) })}
          >
            {t("laws.everyAction")}
          </Button>
          {every.error ? (
            <Notice tone="danger" className="basis-full">
              {t("common.failed")}
            </Notice>
          ) : null}
        </section>
      ) : null}

      {draft ? (
        <div className="sticky bottom-4 flex flex-col gap-3 rounded-[20px] bg-ink p-4 text-white shadow-[0_18px_40px_rgba(17,22,19,0.25)] sm:px-6">
          <div className="flex flex-wrap items-center gap-3.5">
            <div className="min-w-0 flex-[1_1_280px]">
              <div className="font-semibold">{t("laws.unsaved")}</div>
              <div className="text-sm text-[#c2c9c4]">{summary}</div>
            </div>
            <Button
              variant="ghost"
              size="sm"
              className="text-white hover:bg-white/10"
              onClick={discard}
            >
              {t("laws.discard")}
            </Button>
            <Button
              size="sm"
              disabled={busy || shown.size === 0}
              onClick={() =>
                choose.mutate(
                  order.filter((slug) => shown.has(slug)),
                  {
                    onSuccess: () => setDraft(null),
                  },
                )
              }
            >
              {t("laws.save")}
            </Button>
          </div>
          {choose.error ? <Notice tone="danger">{t("common.failed")}</Notice> : null}
        </div>
      ) : null}
    </Panel>
  );
}
