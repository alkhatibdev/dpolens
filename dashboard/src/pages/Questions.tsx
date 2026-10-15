import { CalendarDays, ChevronDown, Download, Eye, EyeOff, Lock, ShieldCheck } from "lucide-react";
import { Fragment, useState } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, useSearchParams } from "react-router";

import type { Question } from "@/api/client";
import {
  useQuestions,
  type Operation,
  type QuestionFilter,
  type Status,
  type Surface,
} from "@/api/logs";
import { useDocuments } from "@/api/queries";
import { Avatar } from "@/components/Avatar";
import { Citation } from "@/components/Citation";
import { FindBox } from "@/components/Filters";
import { LogsTabs } from "@/components/logs/LogsTabs";
import { Redacted } from "@/components/logs/Redacted";
import { PageHeading, TableCard, td, th } from "@/components/Page";
import { PillSelect } from "@/components/PillSelect";
import { Chip, Failed, Loading, Panel } from "@/components/States";
import { Button } from "@/components/ui/button";
import { Popover, PopoverClose, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { en } from "@/i18n/en";
import { download, queryString } from "@/lib/download";
import { formatDate, formatDayHeading, formatNumber, formatTime, languageName } from "@/lib/format";
import { QUERIES_READ_ALL, QUERIES_READ_IDENTITIES, QUERIES_READ_OWN } from "@/lib/permissions";
import { cn } from "@/lib/utils";
import { usePermitted } from "@/session";

type Period = "7" | "30" | "90" | "always";
type From = "everywhere" | Surface;
type Result = "any" | "answered" | "nothing" | "failed";
type What = "questions" | "clauses" | "documents" | "everything";

const DAY = 24 * 60 * 60 * 1000;
const RESULTS: Record<Result, Status[] | undefined> = {
  any: undefined,
  answered: ["ok"],
  nothing: ["no_match"],
  failed: ["refused", "error"],
};
const WHAT: Record<What, Operation[]> = {
  questions: ["search"],
  clauses: ["get_clause", "get_subtree"],
  documents: ["get_document", "list_documents"],
  everything: ["search", "get_clause", "get_subtree", "get_document", "list_documents", "ask"],
};
const SHOWN_RESULTS = 3;

function sinceFor(period: Period): string | undefined {
  return period === "always"
    ? undefined
    : new Date(Date.now() - Number(period) * DAY).toISOString();
}

function ResultChip({ question }: { question: Question }) {
  const { t } = useTranslation();
  switch (question.status) {
    case "ok":
      return <Chip tone="soft">{t("logs.clauses", { count: question.results.length })}</Chip>;
    case "no_match":
      return <Chip tone="warn">{t("logs.foundNothing")}</Chip>;
    case "refused":
      return <Chip tone="warn">{t("logs.refused")}</Chip>;
    default:
      return <Chip tone="warn">{t("logs.failed")}</Chip>;
  }
}

type Kind = keyof typeof en.logs.removedKinds;

function Details({ question }: { question: Question }) {
  const { t } = useTranslation();
  const shown = question.results.slice(0, SHOWN_RESULTS);
  const kinds = [...new Set(question.redaction_types)].map((kind) =>
    kind in en.logs.removedKinds ? t(`logs.removedKinds.${kind as Kind}`) : kind,
  );
  return (
    <div className="flex flex-wrap gap-6 rounded-2xl bg-panel px-5 py-[18px]">
      <div className="min-w-0 flex-[2_1_380px]">
        <div className="mb-2.5 text-sm font-semibold">{t("logs.returned")}</div>
        {question.results.length ? (
          <ol className="flex flex-col gap-2.5">
            {shown.map((result) => {
              return (
                <li
                  key={result.rank}
                  className="grid grid-cols-[24px_minmax(0,1fr)] items-baseline gap-2.5"
                >
                  <span className="text-[13px] font-semibold text-muted tabular-nums">
                    {result.rank}
                  </span>
                  <span className="min-w-0">
                    <code className="block font-mono text-xs break-all text-brand-dark">
                      {result.clause.key}
                    </code>
                    <span className="block text-[13px] text-ink-2">
                      <Citation clause={result.clause} heading />
                      {` · ${languageName(result.clause.lang)}`}
                      {result.clause.version_label
                        ? ` · ${t("logs.version", { version: result.clause.version_label })}`
                        : null}
                    </span>
                  </span>
                </li>
              );
            })}
            {question.results.length > SHOWN_RESULTS ? (
              <li className="ps-[34px] text-[13px] text-muted">
                {t("logs.andMore", { count: question.results.length - SHOWN_RESULTS })}
              </li>
            ) : null}
          </ol>
        ) : (
          <p className="text-sm text-muted">{t("logs.none")}</p>
        )}
      </div>
      <dl className="flex flex-[1_1_240px] flex-col gap-3">
        {question.scope ? (
          <div>
            <dt className="text-xs text-muted">{t("logs.searched")}</dt>
            <dd className="text-sm">
              {question.scope === "selected" ? t("logs.selectedLaws") : t("logs.outside")}
            </dd>
          </div>
        ) : null}
        <div>
          <dt className="text-xs text-muted">{t("logs.takenOut")}</dt>
          <dd className="text-sm">
            {question.redaction_count
              ? t("logs.removedCount", { count: question.redaction_count, what: kinds.join(", ") })
              : t("logs.nothingTakenOut")}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">{t("logs.deletedOn")}</dt>
          <dd className="text-sm">{formatDate(question.expires_at)}</dd>
        </div>
      </dl>
    </div>
  );
}

function Strip({
  readsAll,
  mayName,
  identities,
  onShow,
  onHide,
}: {
  readsAll: boolean;
  mayName: boolean;
  identities: boolean;
  onShow: () => void;
  onHide: () => void;
}) {
  const { t } = useTranslation();
  if (identities) {
    return (
      <div className="flex flex-wrap items-center gap-4 rounded-[20px] bg-ink px-5 py-[18px] text-white">
        <span className="grid size-10 shrink-0 place-items-center rounded-full bg-[#2b332e]">
          <Eye aria-hidden className="size-5" />
        </span>
        <div className="min-w-0 flex-[1_1_360px]">
          <div className="font-semibold">{t("logs.shownTitle")}</div>
          <div className="mt-0.5 text-sm text-[#c2c9c4]">{t("logs.shownBody")}</div>
        </div>
        <Button variant="quiet" size="sm" className="bg-white" onClick={onHide}>
          <EyeOff aria-hidden className="size-4" />
          {t("logs.hideNames")}
        </Button>
      </div>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-4 rounded-[20px] bg-white px-5 py-[18px]">
      <span className="grid size-10 shrink-0 place-items-center rounded-full bg-brand-soft text-brand-dark">
        <ShieldCheck aria-hidden className="size-5" />
      </span>
      <div className="min-w-0 flex-[1_1_360px]">
        <div className="font-semibold">
          {readsAll ? t("logs.hiddenTitle") : t("logs.yoursTitle")}
        </div>
        <div className="mt-0.5 text-sm text-muted">
          {readsAll ? t("logs.hiddenBody") : t("logs.yoursBody")}
        </div>
      </div>
      {mayName ? (
        <Popover>
          <PopoverTrigger asChild>
            <Button variant="outline" size="sm">
              <Eye aria-hidden className="size-4" />
              {t("logs.showWho")}
            </Button>
          </PopoverTrigger>
          <PopoverContent aria-label={t("logs.showTitle")}>
            <div className="text-lg font-semibold">{t("logs.showTitle")}</div>
            <p className="text-sm leading-relaxed text-ink-2">{t("logs.showBody")}</p>
            <div className="flex flex-wrap gap-2">
              <PopoverClose asChild>
                <Button size="sm" onClick={onShow}>
                  {t("logs.showNames")}
                </Button>
              </PopoverClose>
              <PopoverClose asChild>
                <Button variant="ghost" size="sm">
                  {t("common.cancel")}
                </Button>
              </PopoverClose>
            </div>
          </PopoverContent>
        </Popover>
      ) : null}
    </div>
  );
}

export function QuestionsPage() {
  const { t } = useTranslation();
  const can = usePermitted();
  const [params] = useSearchParams();
  const readsAll = can.has(QUERIES_READ_ALL);
  const mayName = readsAll && can.has(QUERIES_READ_IDENTITIES);
  const [identities, setIdentities] = useState(false);
  const [period, setPeriod] = useState<Period>("7");
  const [since, setSince] = useState<string | undefined>(() => sinceFor("7"));
  const [from, setFrom] = useState<From>("everywhere");
  const [result, setResult] = useState<Result>(() =>
    params.get("status") === "no_match" ? "nothing" : "any",
  );
  const [document, setDocument] = useState("any");
  const [what, setWhat] = useState<What>("questions");
  const [words, setWords] = useState("");
  const [askedBy, setAskedBy] = useState("");
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const [open, setOpen] = useState<string | null>(null);
  const documents = useDocuments();

  const filter: QuestionFilter = {
    since,
    surface: from === "everywhere" ? undefined : [from],
    status: RESULTS[result],
    operation: WHAT[what],
    document: document === "any" ? undefined : document,
    q: words.trim() || undefined,
    asked_by: identities ? askedBy.trim() || undefined : undefined,
    identities: identities || undefined,
  };
  const before = cursors[cursors.length - 1] ?? null;
  const questions = useQuestions(filter, before);

  if (!readsAll && !can.has(QUERIES_READ_OWN)) {
    return <Navigate to="/logs/governance" replace />;
  }

  // Any change of filter starts again from the newest.
  function refilter<T>(set: (value: T) => void) {
    return (value: T) => {
      set(value);
      setCursors([null]);
    };
  }

  const page = questions.data;
  const shown = page?.questions ?? [];
  const first = (cursors.length - 1) * 25 + 1;
  const columns = readsAll ? 7 : 6;
  const days = shown.map((question) => formatDayHeading(question.created_at));

  return (
    <Panel>
      <PageHeading
        title={t("logs.title")}
        subtitle={t("logs.subtitle")}
        action={
          <Button onClick={() => void download(`/v1/queries/export${queryString({ ...filter })}`)}>
            <Download aria-hidden className="size-4" />
            {t("logs.export")}
          </Button>
        }
      />
      <LogsTabs questions={page?.total} />
      <Strip
        readsAll={readsAll}
        mayName={mayName}
        identities={identities}
        onShow={() => {
          setIdentities(true);
          setCursors([null]);
        }}
        onHide={() => {
          setIdentities(false);
          setAskedBy("");
          setCursors([null]);
        }}
      />
      <div className="flex flex-wrap items-center gap-2">
        <FindBox label={t("logs.search")} value={words} onChange={refilter(setWords)} />
        {identities ? (
          <FindBox label={t("logs.who")} value={askedBy} onChange={refilter(setAskedBy)} />
        ) : null}
        <PillSelect
          label={t("logs.period")}
          value={period}
          icon={<CalendarDays aria-hidden className="size-4" />}
          onChange={(value) => {
            setPeriod(value);
            setSince(sinceFor(value));
            setCursors([null]);
          }}
          options={[
            { value: "7", label: t("logs.days7") },
            { value: "30", label: t("logs.days30") },
            { value: "90", label: t("logs.days90") },
            { value: "always", label: t("logs.always") },
          ]}
        />
        <PillSelect
          label={t("logs.from")}
          value={from}
          onChange={refilter(setFrom)}
          options={[
            { value: "everywhere", label: t("logs.everywhere") },
            { value: "mcp", label: t("logs.fromAssistant") },
            { value: "dashboard", label: t("logs.fromDashboard") },
            { value: "api", label: t("logs.fromApi") },
          ]}
        />
        <PillSelect
          label={t("logs.result")}
          value={result}
          onChange={refilter(setResult)}
          options={[
            { value: "any", label: t("logs.anyResult") },
            { value: "answered", label: t("logs.answered") },
            { value: "nothing", label: t("logs.nothing") },
            { value: "failed", label: t("logs.refusedOrError") },
          ]}
        />
        <PillSelect
          label={t("logs.document")}
          value={document}
          onChange={refilter(setDocument)}
          options={[
            { value: "any", label: t("logs.anyDocument") },
            ...(documents.data?.documents ?? []).map((item) => ({
              value: item.slug,
              label: item.title,
            })),
          ]}
        />
        <PillSelect
          label={t("logs.what")}
          value={what}
          onChange={refilter(setWhat)}
          options={[
            { value: "questions", label: t("logs.onlyQuestions") },
            { value: "clauses", label: t("logs.clauseReads") },
            { value: "documents", label: t("logs.documentReads") },
            { value: "everything", label: t("logs.everything") },
          ]}
        />
      </div>

      {questions.isPending ? <Loading /> : null}
      {questions.error ? <Failed onRetry={() => void questions.refetch()} /> : null}
      {page ? (
        <TableCard
          footer={
            <div className="flex flex-wrap items-center justify-between gap-3">
              <span>
                {page.total
                  ? t("logs.total", {
                      count: page.total,
                      number: formatNumber(page.total),
                      from: first,
                      to: first + shown.length - 1,
                    })
                  : t("logs.empty")}
              </span>
              <div className="flex gap-2">
                <Button
                  variant="quiet"
                  size="sm"
                  disabled={cursors.length === 1}
                  onClick={() => setCursors((stack) => stack.slice(0, -1))}
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
                      setCursors((stack) => [...stack, next]);
                    }
                  }}
                >
                  {t("logs.next")}
                </Button>
              </div>
            </div>
          }
        >
          <table className="w-full min-w-[1000px] border-collapse">
            <thead>
              <tr>
                <th scope="col" className={th}>
                  {t("logs.when")}
                </th>
                <th scope="col" className={th}>
                  {t("logs.question")}
                </th>
                <th scope="col" className={th}>
                  {t("logs.fromColumn")}
                </th>
                <th scope="col" className={th}>
                  {t("logs.resultColumn")}
                </th>
                <th scope="col" className={th}>
                  {t("logs.firstResult")}
                </th>
                {readsAll ? (
                  <th scope="col" className={th}>
                    {t("logs.who")}
                  </th>
                ) : null}
                <th scope="col" className={th}>
                  <span className="sr-only">{t("logs.details")}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {shown.map((question, index) => {
                const heading = index === 0 || days[index] !== days[index - 1] ? days[index] : null;
                const expanded = open === question.id;
                const firstResult = question.results[0]?.clause;
                return (
                  <Fragment key={question.id}>
                    {heading ? (
                      <tr>
                        <th
                          colSpan={columns}
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
                          "align-top text-ink-2 tabular-nums",
                          expanded && "border-b-0",
                        )}
                      >
                        {formatTime(question.created_at)}
                      </td>
                      <td className={cn(td, "min-w-[280px] align-top", expanded && "border-b-0")}>
                        {question.operation === "search" ? (
                          <Redacted text={question.question} />
                        ) : (
                          <span className="text-ink-2">
                            {t("logs.read", { target: question.target ?? "" })}
                          </span>
                        )}
                      </td>
                      <td
                        className={cn(
                          td,
                          "align-top text-sm whitespace-nowrap text-ink-2",
                          expanded && "border-b-0",
                        )}
                      >
                        {t(`logs.surfaces.${question.surface}`)}
                      </td>
                      <td
                        className={cn(td, "align-top whitespace-nowrap", expanded && "border-b-0")}
                      >
                        <ResultChip question={question} />
                      </td>
                      <td
                        className={cn(td, "align-top whitespace-nowrap", expanded && "border-b-0")}
                      >
                        {firstResult ? (
                          <>
                            <code className="font-mono text-xs text-brand-dark">
                              {firstResult.key}
                            </code>
                            <div className="text-[13px] text-muted">
                              <Citation clause={firstResult} />
                            </div>
                          </>
                        ) : (
                          <span className="text-muted">{t("logs.none")}</span>
                        )}
                      </td>
                      {readsAll ? (
                        <td className={cn(td, "align-top", expanded && "border-b-0")}>
                          {question.asker ? (
                            <span className="inline-flex items-center gap-2 text-sm font-medium whitespace-nowrap">
                              <Avatar
                                name={question.asker.display_name}
                                service={question.asker.kind === "service_account"}
                                size={28}
                              />
                              {question.asker.display_name}
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1.5 text-sm whitespace-nowrap text-muted">
                              <Lock aria-hidden className="size-3.5" />
                              {t("logs.hidden")}
                            </span>
                          )}
                        </td>
                      ) : null}
                      <td className={cn(td, "px-3 py-2 align-middle", expanded && "border-b-0")}>
                        <button
                          type="button"
                          aria-expanded={expanded}
                          aria-label={t("logs.details")}
                          onClick={() => setOpen(expanded ? null : question.id)}
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
                        <td colSpan={columns} className="border-b border-line px-4 pb-[18px]">
                          <Details question={question} />
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
