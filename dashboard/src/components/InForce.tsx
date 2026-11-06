import { useTranslation } from "react-i18next";

import type { Clause, Coming } from "@/api/client";
import { Chip } from "@/components/States";
import { formatDate, isRightToLeft } from "@/lib/format";

/**
 * When a clause's words apply: since when, from when, until when, or that no day is set.
 * A provision is shown before it applies, so a duty can be prepared for, and says so.
 * `always` shows the mark even for words in force with no end, as a clause's own page does.
 */
export function InForce({ clause, always = false }: { clause: Clause; always?: boolean }) {
  const { t } = useTranslation();
  const today = new Date().toISOString().slice(0, 10);
  const since = clause.in_force_from;
  const until = clause.in_force_until;

  if (clause.in_force) {
    return (
      <>
        {always && since ? <Chip>{t("document.inForce", { date: formatDate(since) })}</Chip> : null}
        {until ? (
          <Chip tone="warn">{t("document.inForceUntil", { date: formatDate(until) })}</Chip>
        ) : null}
        {clause.coming && !always ? (
          <Chip tone="soft">
            {t("document.newWordsFrom", { date: formatDate(clause.coming.in_force_from) })}
          </Chip>
        ) : null}
      </>
    );
  }
  if (until && until <= today) {
    return <Chip tone="warn">{t("document.ended", { date: formatDate(until) })}</Chip>;
  }
  if (!since) {
    return <Chip tone="warn">{t("document.noDateYet")}</Chip>;
  }
  return <Chip tone="warn">{t("document.startsLater", { date: formatDate(since) })}</Chip>;
}

/** The words an amendment gives a clause from a later day, quoted as the amendment gives them. */
export function ComingWords({ coming, lang }: { coming: Coming; lang: string }) {
  const { t } = useTranslation();
  return (
    <section className="flex flex-col gap-2.5 rounded-[20px] bg-white px-4 py-4 sm:px-6 sm:py-5">
      <h2 className="text-sm font-semibold text-brand-dark">
        {t("clause.coming", { date: formatDate(coming.in_force_from) })}
      </h2>
      <p
        lang={lang}
        dir={isRightToLeft(lang) ? "rtl" : "ltr"}
        className="text-[15px] leading-relaxed sm:text-base"
      >
        {coming.text}
      </p>
      {coming.dates_set_by ? (
        <p className="text-sm text-muted">
          {t("clause.comingBy", { source: coming.dates_set_by })}
        </p>
      ) : null}
    </section>
  );
}
