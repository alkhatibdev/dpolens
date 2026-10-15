import {
  Check,
  ChevronDown,
  Download,
  KeyRound,
  LogIn,
  RefreshCw,
  Server,
  ShieldAlert,
  ShieldCheck,
  SquareTerminal,
} from "lucide-react";
import { Fragment, useState } from "react";
import { useTranslation } from "react-i18next";
import { Navigate } from "react-router";

import type { Entry } from "@/api/client";
import { useActors, useEntries, useVerification, type Category } from "@/api/logs";
import { Avatar } from "@/components/Avatar";
import { FindBox } from "@/components/Filters";
import { LogsTabs } from "@/components/logs/LogsTabs";
import { Notice } from "@/components/Notice";
import { PageHeading, TableCard, td, th } from "@/components/Page";
import { PillSelect } from "@/components/PillSelect";
import { Chip, Failed, Loading, Panel } from "@/components/States";
import { Button } from "@/components/ui/button";
import { download } from "@/lib/download";
import { formatDayHeading, formatNumber, formatTime, formatWhen } from "@/lib/format";
import { describeEntry } from "@/lib/governance";
import { GOVERNANCE_READ } from "@/lib/permissions";
import { cn } from "@/lib/utils";
import { usePermitted } from "@/session";

type Period = "30" | "90" | "always";
type What = "everything" | Category;

const DAY = 24 * 60 * 60 * 1000;

function sinceFor(period: Period): string | undefined {
  return period === "always"
    ? undefined
    : new Date(Date.now() - Number(period) * DAY).toISOString();
}

function Integrity() {
  const { t } = useTranslation();
  const check = useVerification();
  const report = check.data;
  const broken = report && !report.ok;
  return (
    <div
      className={cn(
        "relative min-w-0 flex-[1_1_420px] overflow-hidden rounded-[20px] px-6 py-[22px]",
        broken ? "bg-danger-soft text-danger-ink" : "bg-brand text-white",
      )}
    >
      {broken ? null : (
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
      )}
      <div className="relative flex items-center gap-3">
        <span
          className={cn(
            "grid size-10 place-items-center rounded-full",
            broken ? "bg-white text-danger-ink" : "bg-white text-brand-dark",
          )}
        >
          {broken ? (
            <ShieldAlert aria-hidden className="size-5" />
          ) : (
            <ShieldCheck aria-hidden className="size-5" />
          )}
        </span>
        <span className="font-medium">
          {!report ? t("logs.checking") : broken ? t("logs.brokenTitle") : t("logs.intactTitle")}
        </span>
      </div>
      {report ? (
        <>
          <div className="relative mt-4 text-[44px] leading-none font-semibold tracking-[-0.03em] tabular-nums sm:text-[52px]">
            {t("logs.intactEntries", {
              count: report.entries,
              number: formatNumber(report.entries),
            })}
          </div>
          <p
            className={cn(
              "relative mt-2 max-w-[46ch] text-sm leading-relaxed",
              broken ? "" : "text-brand-soft",
            )}
          >
            {report.first_broken_seq
              ? t("logs.brokenBody", { seq: report.first_broken_seq, reason: report.reason ?? "" })
              : report.out_of_order.length
                ? t("logs.disorderBody")
                : t("logs.intactBody", { when: formatWhen(report.checked_at) })}
          </p>
        </>
      ) : (
        <div className="relative mt-4 h-[84px] animate-pulse rounded-xl bg-white/15" />
      )}
      {check.error ? <Failed onRetry={() => void check.refetch()} /> : null}
      <Button
        variant="quiet"
        size="sm"
        className="relative mt-4 bg-white text-ink"
        disabled={check.isFetching}
        onClick={() => void check.refetch()}
      >
        <RefreshCw aria-hidden className={cn("size-4", check.isFetching && "animate-spin")} />
        {t("logs.checkAgain")}
      </Button>
    </div>
  );
}

function Holds() {
  const { t } = useTranslation();
  const items = ["signIns", "people", "tokens", "laws", "looks", "exports"] as const;
  return (
    <section className="min-w-0 flex-[1_1_360px] rounded-[20px] bg-white px-6 py-[22px]">
      <h2 className="text-xl font-semibold">{t("logs.holdsTitle")}</h2>
      <ul className="mt-3.5 grid grid-cols-1 gap-x-5 gap-y-2.5 text-sm text-ink-2 sm:grid-cols-2">
        {items.map((item) => (
          <li key={item} className="flex items-start gap-2">
            <Check aria-hidden className="mt-0.5 size-4 shrink-0 text-brand" />
            {t(`logs.holds.${item}`)}
          </li>
        ))}
      </ul>
      <p className="mt-4 text-sm text-muted">{t("logs.noEdits")}</p>
    </section>
  );
}

function Who({ entry }: { entry: Entry }) {
  const { t } = useTranslation();
  const details = entry.details as Record<string, unknown>;
  const icon = (Icon: typeof KeyRound) => (
    <span
      aria-hidden
      className="grid size-7 shrink-0 place-items-center rounded-full bg-field text-ink-2"
    >
      <Icon className="size-4" />
    </span>
  );
  if (entry.actor) {
    return (
      <span className="inline-flex items-center gap-2 text-sm font-medium whitespace-nowrap">
        <Avatar
          name={entry.actor.display_name}
          service={entry.actor.kind === "service_account"}
          size={28}
        />
        {entry.actor.display_name}
      </span>
    );
  }
  let face = icon(Server);
  let name: string = t("logs.actors.instance");
  let sub: string | null = null;
  if (entry.actor_token) {
    face = icon(KeyRound);
    name = t("logs.actors.token");
    sub = `${entry.actor_token.prefix}…`;
  } else if (details.via === "cli") {
    const who = (details.actor ?? {}) as Record<string, unknown>;
    face = icon(SquareTerminal);
    name = t("logs.actors.cli");
    sub = t("logs.actors.cliWhere", {
      user: String(who.os_user ?? ""),
      host: String(who.host ?? ""),
    });
  } else if (details.via === "dashboard") {
    face = icon(LogIn);
    name = t("logs.actors.signInPage");
  }
  return (
    <span className="inline-flex items-center gap-2 text-sm font-medium whitespace-nowrap">
      {face}
      <span>
        {name}
        {sub ? <span className="block text-xs font-normal text-muted">{sub}</span> : null}
      </span>
    </span>
  );
}

function Change({ entry }: { entry: Entry }) {
  const { t } = useTranslation();
  const details = entry.details as Record<string, unknown>;
  const before = Array.isArray(details.before) ? (details.before as string[]) : null;
  const after = Array.isArray(details.after) ? (details.after as string[]) : null;
  const shown = Object.entries(details).filter(
    ([key]) => !["via", "actor", "before", "after"].includes(key),
  );
  const chips = (keys: string[], added: string[] = []) => (
    <div className="flex flex-wrap gap-1.5">
      {keys.map((key) => (
        <Chip key={key} tone={added.includes(key) ? "brand" : "quiet"}>
          <code className="font-mono text-xs">{key}</code>
        </Chip>
      ))}
    </div>
  );
  return (
    <div className="flex flex-col gap-4 rounded-2xl bg-panel px-5 py-[18px]">
      {before && after ? (
        <div className="flex flex-wrap gap-6">
          <div className="min-w-0 flex-[1_1_320px]">
            <div className="mb-2 text-[13px] text-muted">{t("logs.before")}</div>
            {chips(before)}
          </div>
          <div className="min-w-0 flex-[1_1_320px]">
            <div className="mb-2 text-[13px] text-muted">{t("logs.after")}</div>
            {chips(
              after,
              after.filter((key) => !before.includes(key)),
            )}
          </div>
        </div>
      ) : null}
      {shown.length ? (
        <dl className="grid grid-cols-[repeat(auto-fill,minmax(min(100%,220px),1fr))] gap-3">
          {shown.map(([key, value]) => (
            <div key={key} className="min-w-0">
              <dt className="font-mono text-xs text-muted">{key}</dt>
              <dd className="text-sm break-words">
                {typeof value === "object" ? JSON.stringify(value) : String(value)}
              </dd>
            </div>
          ))}
        </dl>
      ) : null}
      <div className="flex flex-wrap gap-x-6 gap-y-2 border-t border-line pt-3.5 text-[13px] text-muted">
        <span>
          {t("logs.action")} <code className="font-mono text-xs text-ink-2">{entry.action}</code>
        </span>
        <span>
          {t("logs.target")}{" "}
          <code className="font-mono text-xs break-all text-ink-2">
            {entry.target_type} {entry.target_id}
          </code>
        </span>
        <span>
          {t("logs.previousHash")}{" "}
          <code className="font-mono text-xs text-ink-2">{entry.prev_hash.slice(0, 12)}…</code>
        </span>
        <span>
          {t("logs.thisHash")}{" "}
          <code className="font-mono text-xs text-ink-2">{entry.entry_hash.slice(0, 12)}…</code>
        </span>
      </div>
    </div>
  );
}

export function GovernancePage() {
  const { t } = useTranslation();
  const can = usePermitted();
  const [words, setWords] = useState("");
  const [actor, setActor] = useState("anyone");
  const [what, setWhat] = useState<What>("everything");
  const [period, setPeriod] = useState<Period>("30");
  const [since, setSince] = useState<string | undefined>(() => sinceFor("30"));
  const [befores, setBefores] = useState<(number | null)[]>([null]);
  const [open, setOpen] = useState<number | null>(null);
  const [exportFailed, setExportFailed] = useState(false);
  const allowed = can.has(GOVERNANCE_READ);
  const actors = useActors();
  const entries = useEntries(
    {
      actor: actor === "anyone" ? undefined : actor,
      category: what === "everything" ? undefined : [what],
      since,
      q: words.trim() || undefined,
    },
    befores[befores.length - 1] ?? null,
  );

  if (!allowed) {
    return <Navigate to="/logs" replace />;
  }

  function refilter<T>(set: (value: T) => void) {
    return (value: T) => {
      set(value);
      setBefores([null]);
    };
  }

  const page = entries.data;
  const shown = page?.entries ?? [];
  const days = shown.map((entry) => formatDayHeading(entry.occurred_at));
  const first = (befores.length - 1) * 25 + 1;
  const categories: Category[] = [
    "sign_ins",
    "people",
    "roles",
    "tokens",
    "laws",
    "questions",
    "exports",
  ];

  return (
    <Panel>
      <PageHeading
        title={t("logs.title")}
        subtitle={t("logs.subtitle")}
        action={
          <Button
            onClick={() => {
              setExportFailed(false);
              download("/v1/governance/exports", { method: "POST" }).catch(() =>
                setExportFailed(true),
              );
            }}
          >
            <Download aria-hidden className="size-4" />
            {t("logs.exportAudit")}
          </Button>
        }
      />
      <LogsTabs governance={page?.total} />
      {exportFailed ? <Notice tone="danger">{t("common.failed")}</Notice> : null}
      <div className="flex flex-wrap gap-4">
        <Integrity />
        <Holds />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <FindBox label={t("logs.searchEntries")} value={words} onChange={refilter(setWords)} />
        <PillSelect
          label={t("logs.whoFilter")}
          value={actor}
          onChange={refilter(setActor)}
          options={[
            { value: "anyone", label: t("logs.anyone") },
            ...(actors.data?.people ?? []).map((person) => ({
              value: person.id,
              label: `${t("logs.whoFilter")}: ${person.display_name}`,
            })),
          ]}
        />
        <PillSelect
          label={t("logs.whatFilter")}
          value={what}
          onChange={refilter(setWhat)}
          options={[
            { value: "everything", label: t("logs.everything") },
            ...categories.map((category) => ({
              value: category,
              label: t(`logs.categories.${category}`),
            })),
          ]}
        />
        <PillSelect
          label={t("logs.period")}
          value={period}
          onChange={(value) => {
            setPeriod(value);
            setSince(sinceFor(value));
            setBefores([null]);
          }}
          options={[
            { value: "30", label: t("logs.days30") },
            { value: "90", label: t("logs.days90") },
            { value: "always", label: t("logs.always") },
          ]}
        />
      </div>

      {entries.isPending ? <Loading /> : null}
      {entries.error ? <Failed onRetry={() => void entries.refetch()} /> : null}
      {page ? (
        <TableCard
          footer={
            <div className="flex flex-wrap items-center justify-between gap-3">
              <span>
                {page.total
                  ? `${t("logs.entriesTotal", {
                      count: page.total,
                      number: formatNumber(page.total),
                      from: first,
                      to: first + shown.length - 1,
                    })} ${t("logs.zoneNote")}`
                  : t("logs.noEntries")}
              </span>
              <div className="flex gap-2">
                <Button
                  variant="quiet"
                  size="sm"
                  disabled={befores.length === 1}
                  onClick={() => setBefores((stack) => stack.slice(0, -1))}
                >
                  {t("logs.previous")}
                </Button>
                <Button
                  variant="quiet"
                  size="sm"
                  disabled={!page.next}
                  onClick={() => {
                    const next = page.next;
                    if (next) {
                      setBefores((stack) => [...stack, next]);
                    }
                  }}
                >
                  {t("logs.next")}
                </Button>
              </div>
            </div>
          }
        >
          <table className="w-full min-w-[980px] border-collapse">
            <thead>
              <tr>
                <th scope="col" className={th}>
                  {t("logs.number")}
                </th>
                <th scope="col" className={th}>
                  {t("logs.time")}
                </th>
                <th scope="col" className={th}>
                  {t("logs.who")}
                </th>
                <th scope="col" className={th}>
                  {t("logs.whatHappened")}
                </th>
                <th scope="col" className={th}>
                  {t("logs.hash")}
                </th>
                <th scope="col" className={th}>
                  <span className="sr-only">{t("logs.showChange")}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {shown.map((entry, index) => {
                const heading = index === 0 || days[index] !== days[index - 1] ? days[index] : null;
                const expanded = open === entry.seq;
                const refused =
                  entry.action === "pat.rejected" || entry.action === "session.refused";
                return (
                  <Fragment key={entry.seq}>
                    {heading ? (
                      <tr>
                        <th
                          colSpan={6}
                          scope="colgroup"
                          className="px-4 pt-4 pb-1.5 text-start text-[13px] font-semibold text-ink-2"
                        >
                          {heading}
                        </th>
                      </tr>
                    ) : null}
                    <tr>
                      <td
                        className={cn(
                          td,
                          "text-[13px] text-muted tabular-nums",
                          expanded && "border-b-0",
                        )}
                      >
                        {entry.seq}
                      </td>
                      <td
                        className={cn(
                          td,
                          "whitespace-nowrap text-ink-2 tabular-nums",
                          expanded && "border-b-0",
                        )}
                      >
                        {formatTime(entry.occurred_at)}
                      </td>
                      <td className={cn(td, expanded && "border-b-0")}>
                        <Who entry={entry} />
                      </td>
                      <td className={cn(td, "min-w-[300px]", expanded && "border-b-0")}>
                        {describeEntry(t, entry)}{" "}
                        {refused ? <Chip tone="warn">{t("logs.refusedTag")}</Chip> : null}
                        {entry.action.startsWith("query_log.identities") ? (
                          <Chip tone="quiet">{t("logs.questions")}</Chip>
                        ) : null}
                      </td>
                      <td className={cn(td, "whitespace-nowrap", expanded && "border-b-0")}>
                        <code className="font-mono text-xs text-muted">
                          {entry.entry_hash.slice(0, 4)}…{entry.entry_hash.slice(-4)}
                        </code>
                      </td>
                      <td className={cn(td, "px-3 py-2", expanded && "border-b-0")}>
                        <button
                          type="button"
                          aria-expanded={expanded}
                          aria-label={t("logs.showChange")}
                          onClick={() => setOpen(expanded ? null : entry.seq)}
                          className={cn(
                            "grid size-9 place-items-center rounded-full text-ink-2 hover:bg-field",
                            expanded && "bg-field",
                          )}
                        >
                          <ChevronDown
                            aria-hidden
                            className={cn("size-[18px]", expanded && "rotate-180")}
                          />
                        </button>
                      </td>
                    </tr>
                    {expanded ? (
                      <tr>
                        <td colSpan={6} className="border-b border-line px-4 pb-[18px]">
                          <Change entry={entry} />
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </TableCard>
      ) : null}
    </Panel>
  );
}
