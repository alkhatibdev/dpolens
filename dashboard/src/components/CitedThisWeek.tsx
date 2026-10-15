import { useTranslation } from "react-i18next";

import { useClauseActivity } from "@/api/logs";
import { QUERIES_READ_ALL } from "@/lib/permissions";
import { usePermitted } from "@/session";

const weekday = new Intl.DateTimeFormat("en-GB", { weekday: "long", timeZone: "UTC" });

/** How often this clause was cited in the last seven days, for whoever may read every question. */
export function CitedThisWeek({ clauseKey }: { clauseKey: string }) {
  const { t } = useTranslation();
  const can = usePermitted();
  const allowed = can.has(QUERIES_READ_ALL);
  const activity = useClauseActivity(clauseKey, allowed);
  if (!allowed || !activity.data) {
    return null;
  }
  const highest = Math.max(1, ...activity.data.by_day.map((day) => day.count));
  return (
    <section
      aria-label={t("clause.citedThisWeek")}
      className="flex items-end justify-between gap-3 rounded-[20px] bg-brand px-[22px] py-5 text-white"
    >
      <div>
        <div className="text-[15px] font-medium">{t("clause.citedThisWeek")}</div>
        <div className="mt-1.5 text-[44px] leading-[1.1] font-semibold tracking-[-0.03em] tabular-nums">
          {activity.data.total}
        </div>
      </div>
      <div
        role="img"
        aria-label={t("clause.citedByDay", {
          days: activity.data.by_day
            .map((day) => `${weekday.format(new Date(`${day.day}T00:00:00Z`))} ${day.count}`)
            .join(", "),
        })}
        className="flex h-16 items-end gap-1.5"
      >
        {activity.data.by_day.map((day) => (
          <span
            key={day.day}
            className="w-3.5 rounded-full bg-white"
            style={{
              height: Math.max(6, Math.round((day.count / highest) * 64)),
              opacity: day.count === highest && day.count > 0 ? 1 : 0.5,
            }}
          />
        ))}
      </div>
    </section>
  );
}
