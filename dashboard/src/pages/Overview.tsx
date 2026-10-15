import { ArrowUpRight, CalendarDays, MessageCircleQuestion } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, Navigate } from "react-router";

import type { Overview } from "@/api/client";
import { useOverview } from "@/api/logs";
import { Citation } from "@/components/Citation";
import { Redacted } from "@/components/logs/Redacted";
import { PageHeading } from "@/components/Page";
import { PillSelect } from "@/components/PillSelect";
import { Chip, Failed, Loading, Panel } from "@/components/States";
import { sourceName } from "@/lib/clauseName";
import { formatNumber, formatSince } from "@/lib/format";
import { QUERIES_READ_ALL } from "@/lib/permissions";
import { cn } from "@/lib/utils";
import { usePermitted } from "@/session";

type Range = "7" | "30" | "90";

const weekday = new Intl.DateTimeFormat("en-GB", { weekday: "short", timeZone: "UTC" });
const shortDate = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  timeZone: "UTC",
});

/** One link in a tile's corner: a circle with an arrow, white on the brand tile. */
function Corner({ to, label, onBrand = false }: { to: string; label: string; onBrand?: boolean }) {
  return (
    <Link
      to={to}
      aria-label={label}
      className={cn(
        "relative grid size-10 shrink-0 place-items-center rounded-full",
        onBrand ? "bg-white text-ink" : "border-[1.5px] border-ink text-ink",
      )}
    >
      <ArrowUpRight aria-hidden className="size-4" />
    </Link>
  );
}

function Tile({
  label,
  value,
  note,
  to,
  linkLabel,
  brand = false,
}: {
  label: string;
  value: string;
  note: string;
  to: string;
  linkLabel: string;
  brand?: boolean;
}) {
  return (
    <div
      className={cn(
        "relative min-h-[168px] overflow-hidden rounded-[20px] p-5",
        brand ? "bg-brand text-white" : "bg-white",
      )}
    >
      {brand ? (
        <svg
          aria-hidden
          viewBox="0 0 260 260"
          className="absolute -right-[90px] -bottom-[110px] size-[260px]"
          fill="none"
          stroke="#ffffff"
          strokeOpacity="0.13"
          strokeWidth="1.5"
        >
          {[40, 70, 100, 128].map((r) => (
            <circle key={r} cx="130" cy="130" r={r} />
          ))}
        </svg>
      ) : null}
      <div className="relative flex items-start justify-between gap-3">
        <span className="font-medium">{label}</span>
        <Corner to={to} label={linkLabel} onBrand={brand} />
      </div>
      <div className="relative mt-[18px] text-[44px] leading-none font-semibold tracking-[-0.03em] tabular-nums sm:text-[52px]">
        {value}
      </div>
      <div className={cn("relative mt-2 text-[13px]", brand ? "text-brand-soft" : "text-muted")}>
        {note}
      </div>
    </div>
  );
}

interface Bar {
  label: string;
  total: number;
  assistants: number;
  today: boolean;
}

/** Days for a week; weeks for anything longer, so a bar stays wide enough to read. */
function barsOf(overview: Overview, todayLabel: string): Bar[] {
  const days = overview.by_day.map((day, index) => ({
    day,
    total: day.assistants + day.dashboard + day.other,
    last: index === overview.by_day.length - 1,
  }));
  if (days.length <= 14) {
    return days.map(({ day, total, last }) => ({
      label: last ? todayLabel : weekday.format(new Date(`${day.day}T00:00:00Z`)),
      total,
      assistants: day.assistants,
      today: last,
    }));
  }
  const weeks: Bar[] = [];
  for (let start = 0; start < days.length; start += 7) {
    const chunk = days.slice(start, start + 7);
    weeks.push({
      label: shortDate.format(new Date(`${chunk[0]?.day.day ?? ""}T00:00:00Z`)),
      total: chunk.reduce((sum, item) => sum + item.total, 0),
      assistants: chunk.reduce((sum, item) => sum + item.day.assistants, 0),
      today: chunk.some((item) => item.last),
    });
  }
  return weeks;
}

function ByDay({ overview }: { overview: Overview }) {
  const { t } = useTranslation();
  const bars = barsOf(overview, t("overview.today"));
  const highest = Math.max(1, ...bars.map((bar) => bar.total));
  const peak = bars.findIndex((bar) => bar.total === highest);
  const assistants = bars.reduce((sum, bar) => sum + bar.assistants, 0);
  return (
    <section className="min-w-0 flex-[2_1_520px] rounded-[20px] bg-white px-6 pt-[22px] pb-[18px]">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xl font-semibold">{t("overview.byDay")}</h2>
        <div className="flex flex-wrap gap-4 text-[13px] text-ink-2">
          <span className="flex items-center gap-1.5">
            <span aria-hidden className="size-3 rounded bg-brand" />
            {t("overview.fromAssistants")}
          </span>
          <span className="flex items-center gap-1.5">
            <span aria-hidden className="stripes size-3 rounded" />
            {t("overview.fromElsewhere")}
          </span>
        </div>
      </div>
      <div
        role="img"
        aria-label={t("overview.byDayLabel", {
          days: bars.map((bar) => `${bar.label} ${bar.total}`).join(", "),
          assistants,
        })}
        className="mt-10 grid h-[250px] items-end gap-2 sm:gap-3.5"
        style={{ gridTemplateColumns: `repeat(${bars.length}, minmax(0, 1fr))` }}
      >
        {bars.map((bar, index) => {
          const outer = Math.max(bar.total ? 10 : 6, Math.round((bar.total / highest) * 210));
          const inner = bar.total ? Math.round((bar.assistants / bar.total) * outer) : 0;
          return (
            <div
              key={`${bar.label}-${index}`}
              className="relative flex flex-col items-center gap-2.5"
            >
              {index === peak && bar.total > 0 ? (
                <span className="absolute -top-[30px] rounded-lg bg-ink px-2 py-1 text-xs font-semibold text-white tabular-nums">
                  {bar.total}
                </span>
              ) : null}
              <div
                className="stripes flex w-full max-w-16 flex-col justify-end overflow-hidden rounded-full"
                style={{ height: outer }}
              >
                <div
                  className={cn("rounded-full", index === peak ? "bg-brand" : "bg-brand-deep")}
                  style={{ height: inner }}
                />
              </div>
              <span
                className={cn(
                  "text-xs whitespace-nowrap sm:text-sm",
                  bar.today || index === peak ? "font-semibold text-ink" : "text-muted",
                )}
              >
                {bar.label}
              </span>
            </div>
          );
        })}
      </div>
    </section>
  );
}

const ARC = Math.PI * 90;
const SOURCE_COLOURS = [
  "var(--color-brand)",
  "var(--color-brand-deep)",
  "var(--color-brand-dark)",
  "var(--color-brand-mid)",
];

function Sources({ overview }: { overview: Overview }) {
  const { t } = useTranslation();
  const total = Math.max(1, overview.questions);
  const parts = overview.sources.map((source, index) => ({
    name: source.pack_slug
      ? sourceName(source.pack_slug, source.title)
      : t("overview.yourPolicies"),
    share: source.count / total,
    colour: SOURCE_COLOURS[index % SOURCE_COLOURS.length] ?? "var(--color-brand)",
  }));
  const nothing = overview.found_nothing / total;
  const percent = (share: number) => Math.round(share * 100);
  const arcs = parts.map((part, index) => ({
    ...part,
    length: part.share * ARC,
    offset: parts.slice(0, index).reduce((sum, earlier) => sum + earlier.share * ARC, 0),
  }));
  const offset = parts.reduce((sum, part) => sum + part.share * ARC, 0);
  const found = Math.round((overview.answered / total) * 100);
  return (
    <section className="flex min-w-0 flex-[1_1_300px] flex-col rounded-[20px] bg-white px-6 py-[22px]">
      <h2 className="text-xl font-semibold">{t("overview.sources")}</h2>
      <svg
        role="img"
        aria-label={t("overview.sourcesLabel", {
          parts: parts
            .map((part) => t("overview.share", { name: part.name, percent: percent(part.share) }))
            .join(", "),
          nothing: percent(nothing),
        })}
        viewBox="0 0 220 130"
        className="mt-3.5 h-[150px] w-full"
      >
        <defs>
          <pattern
            id="nothing-stripes"
            width="8"
            height="8"
            patternUnits="userSpaceOnUse"
            patternTransform="rotate(45)"
          >
            <rect width="8" height="8" fill="var(--color-brand-soft)" />
            <rect width="4" height="8" fill="var(--color-brand-mid)" />
          </pattern>
        </defs>
        <path
          d="M20 112 A90 90 0 0 1 200 112"
          fill="none"
          stroke="var(--color-line)"
          strokeWidth="28"
        />
        {arcs.map((arc) => (
          <path
            key={arc.name}
            d="M20 112 A90 90 0 0 1 200 112"
            fill="none"
            stroke={arc.colour}
            strokeWidth="28"
            strokeDasharray={`${arc.length} 400`}
            strokeDashoffset={-arc.offset}
          />
        ))}
        <path
          d="M20 112 A90 90 0 0 1 200 112"
          fill="none"
          stroke="url(#nothing-stripes)"
          strokeWidth="28"
          strokeDasharray={`${nothing * ARC} 400`}
          strokeDashoffset={-offset}
        />
        <text
          x="110"
          y="100"
          textAnchor="middle"
          fontSize="34"
          fontWeight="600"
          fill="var(--color-ink)"
        >
          {found}%
        </text>
        <text x="110" y="122" textAnchor="middle" fontSize="12" fill="var(--color-muted)">
          {t("overview.foundAClause")}
        </text>
      </svg>
      <ul className="mt-auto grid grid-cols-2 gap-x-[18px] gap-y-2.5 pt-3.5 text-[13px] text-ink-2">
        {parts.map((part) => (
          <li key={part.name} className="flex items-center gap-1.5">
            <span aria-hidden className="size-3 rounded-full" style={{ background: part.colour }} />
            {t("overview.share", { name: part.name, percent: percent(part.share) })}
          </li>
        ))}
        <li className="flex items-center gap-1.5">
          <span aria-hidden className="stripes size-3 rounded-full" />
          {t("overview.share", { name: t("overview.nothingInForce"), percent: percent(nothing) })}
        </li>
      </ul>
    </section>
  );
}

function MostCited({ overview }: { overview: Overview }) {
  const { t } = useTranslation();
  const highest = Math.max(1, ...overview.most_cited.map((cited) => cited.count));
  return (
    <section className="min-w-0 flex-[1_1_420px] rounded-[20px] bg-white px-6 py-[22px]">
      <h2 className="text-xl font-semibold">{t("overview.mostCited")}</h2>
      <p className="mt-1.5 text-sm text-muted">{t("overview.mostCitedNote")}</p>
      <ul className="mt-2 flex flex-col">
        {overview.most_cited.map((cited) => (
          // On a phone the bar goes under the name, so the name keeps the width it needs.
          <li
            key={cited.clause.key}
            className="grid grid-cols-[minmax(0,1fr)_44px] items-center gap-x-4 gap-y-2 border-b border-line py-3 last:border-b-0 sm:grid-cols-[minmax(0,1fr)_minmax(60px,140px)_44px]"
          >
            <Link
              to={`/clauses/${encodeURIComponent(cited.clause.key)}`}
              className="col-span-2 min-w-0 hover:underline sm:col-span-1"
            >
              <code className="block font-mono text-[13px] break-all text-brand-dark">
                {cited.clause.key}
              </code>
              <span className="mt-0.5 block text-[15px]">
                <Citation clause={cited.clause} heading />
              </span>
            </Link>
            <span aria-hidden className="h-2.5 overflow-hidden rounded-full bg-line">
              <span
                className="block h-full rounded-full bg-brand"
                style={{ width: `${Math.round((cited.count / highest) * 100)}%` }}
              />
            </span>
            <span className="text-end text-[15px] font-semibold tabular-nums">{cited.count}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Unanswered({ overview }: { overview: Overview }) {
  const { t } = useTranslation();
  return (
    <section className="min-w-0 flex-[1_1_420px] rounded-[20px] bg-white px-6 py-[22px]">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 className="text-xl font-semibold">{t("overview.unanswered")}</h2>
        {overview.found_nothing ? (
          <Link
            to="/logs?status=no_match"
            className="text-sm font-medium text-brand-dark underline underline-offset-2"
          >
            {t("overview.openAll", {
              count: overview.found_nothing,
              number: formatNumber(overview.found_nothing),
            })}
          </Link>
        ) : null}
      </div>
      <p className="mt-1.5 text-sm text-muted">{t("overview.unansweredNote")}</p>
      {overview.unanswered.length ? (
        <ul className="mt-2 flex flex-col">
          {overview.unanswered.map((question) => (
            <li
              key={question.id}
              className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-0.5 border-b border-line py-3 last:border-b-0"
            >
              <span className="min-w-0 text-[15px] leading-normal">
                <Redacted text={question.question} />
              </span>
              <span className="text-sm whitespace-nowrap text-muted">
                {t(`logs.surfaces.${question.surface}`)} · {formatSince(question.created_at)}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-4 text-[15px] text-ink-2">{t("overview.noneUnanswered")}</p>
      )}
    </section>
  );
}

function change(t: ReturnType<typeof useTranslation>["t"], overview: Overview): string {
  if (!overview.previous_questions) {
    return t("overview.firstWeek");
  }
  const delta = Math.round(
    ((overview.questions - overview.previous_questions) / overview.previous_questions) * 100,
  );
  if (delta > 0) {
    return t("overview.more", { percent: delta, days: overview.days });
  }
  if (delta < 0) {
    return t("overview.fewer", { percent: -delta, days: overview.days });
  }
  return t("overview.same", { days: overview.days });
}

export function OverviewPage() {
  const { t } = useTranslation();
  const can = usePermitted();
  const [range, setRange] = useState<Range>("7");
  const allowed = can.has(QUERIES_READ_ALL);
  const overview = useOverview(Number(range), allowed);

  if (!allowed) {
    return <Navigate to="/library" replace />;
  }

  const data = overview.data;
  return (
    <Panel>
      <PageHeading
        title={t("overview.title")}
        subtitle={t("overview.subtitle", { days: range })}
        action={
          <PillSelect
            label={t("overview.range")}
            value={range}
            onChange={setRange}
            icon={<CalendarDays aria-hidden className="size-4" />}
            options={[
              { value: "7", label: t("overview.days7") },
              { value: "30", label: t("overview.days30") },
              { value: "90", label: t("overview.days90") },
            ]}
          />
        }
      />
      {overview.isPending ? <Loading /> : null}
      {overview.error ? <Failed onRetry={() => void overview.refetch()} /> : null}
      {data ? (
        <>
          <div className="grid grid-cols-[repeat(auto-fit,minmax(220px,1fr))] gap-4">
            <Tile
              brand
              label={t("overview.questions")}
              value={formatNumber(data.questions)}
              note={change(t, data)}
              to="/logs"
              linkLabel={t("overview.openQuestions")}
            />
            <Tile
              label={t("overview.answered")}
              value={
                data.questions ? `${Math.round((data.answered / data.questions) * 100)}%` : "-"
              }
              note={t("overview.foundNothing", {
                count: data.found_nothing,
                number: formatNumber(data.found_nothing),
              })}
              to="/logs?status=no_match"
              linkLabel={t("overview.openUnanswered")}
            />
            <Tile
              label={t("overview.laws")}
              value={String(data.laws.length)}
              note={data.laws.map((law) => sourceName(law.slug, law.name)).join(", ")}
              to="/library"
              linkLabel={t("overview.openLaws")}
            />
          </div>
          {data.questions === 0 ? (
            <div className="flex flex-col items-start gap-2.5 rounded-[20px] border-2 border-dashed border-line-strong p-6">
              <MessageCircleQuestion aria-hidden className="size-8 text-brand-dark" />
              <h2 className="text-[19px] font-semibold">{t("overview.nothingYet")}</h2>
              <p className="max-w-[62ch] text-[15px] leading-relaxed text-muted">
                {t("overview.nothingYetBody")}
              </p>
              <Chip tone="soft">
                <Link to="/tokens">{t("nav.tokens")}</Link>
              </Chip>
            </div>
          ) : (
            <>
              <div className="flex flex-wrap gap-4">
                <ByDay overview={data} />
                <Sources overview={data} />
              </div>
              <div className="flex flex-wrap gap-4">
                <MostCited overview={data} />
                <Unanswered overview={data} />
              </div>
            </>
          )}
        </>
      ) : null}
    </Panel>
  );
}
