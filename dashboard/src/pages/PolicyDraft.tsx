import { ArrowLeftRight, Check, Heading, ListIndentIncrease, Pencil } from "lucide-react";
import { useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link, Navigate, useNavigate, useParams } from "react-router";

import { ApiError } from "@/api/client";
import {
  useAcceptFlags,
  useDraft,
  useFixClause,
  usePolicies,
  usePolicyFile,
  type DraftClause,
  type DraftFlag,
  type Edit,
  type FlagSuggestion,
  type PolicyDraft,
} from "@/api/policies";
import { Notice } from "@/components/Notice";
import { SegmentedChoice } from "@/components/Segmented";
import { Chip, Failed, Loading, Panel } from "@/components/States";
import { ClauseTree, Toolbox, type Splitting } from "@/components/policies/ClauseTree";
import {
  ConflictDialog,
  DetailsDialog,
  DiscardDialog,
  PublishDialog,
  RejectDialog,
} from "@/components/policies/DraftDialogs";
import { FileAsRead, type Marks } from "@/components/policies/FileAsRead";
import { FlagCard, small } from "@/components/policies/FlagCard";
import { WhatChanged } from "@/components/policies/WhatChanged";
import { Button } from "@/components/ui/button";
import { formatDate, formatNumber, formatWhen, isRightToLeft } from "@/lib/format";
import { DOCUMENTS_PUBLISH, DOCUMENTS_UPLOAD } from "@/lib/permissions";
import {
  conflictOf,
  isolate,
  isSettled,
  openCount,
  placeOf,
  shortKey,
  walk,
  type Conflict,
} from "@/lib/policies";
import { cn } from "@/lib/utils";
import type { Published } from "@/pages/Policies";
import { usePermitted } from "@/session";

type Tab = "changes" | "file";

function Stat({
  value,
  label,
  note,
  tone,
}: {
  value: ReactNode;
  label: string;
  note: string;
  tone?: "good" | "warn";
}) {
  return (
    <div className="min-w-0 flex-[1_1_200px]">
      <div className="text-[13px] text-muted">{label}</div>
      <div
        className={cn(
          "mt-1 text-[22px] font-semibold tracking-[-0.01em]",
          tone === "good" && "text-brand-dark",
          tone === "warn" && "text-warn-ink",
        )}
      >
        {value}
      </div>
      <div className="mt-0.5 text-[13px] leading-snug text-muted">{note}</div>
    </div>
  );
}

/** The checks every parse runs: whether the file was read in full, the tree, the flags. */
function Checks({ draft }: { draft: PolicyDraft }) {
  const { t } = useTranslation();
  const coverage = draft.coverage;
  const clauses = walk(draft.clauses);
  const open = openCount(draft);
  const layers = (["native_structure", "typography", "numbering", "reviewer"] as const).filter(
    (layer) => clauses.some((clause) => (clause.layer ?? "native_structure") === layer),
  );
  const complete = coverage.missed === 0;
  return (
    <section className="flex flex-wrap gap-[18px] rounded-[20px] bg-white px-[22px] py-[18px]">
      <Stat
        label={t("review.theFileStat")}
        value={complete ? t("review.readInFull") : t("review.notInFull")}
        tone={complete ? "good" : "warn"}
        note={
          complete
            ? t("review.coverage", {
                inClauses: formatNumber(coverage.in_clauses),
                setAside: formatNumber(coverage.set_aside),
              })
            : t("review.missed", { count: coverage.missed })
        }
      />
      <Stat
        label={t("review.theTree")}
        value={t("review.clauses", { count: clauses.length })}
        note={t("review.treeFrom", {
          layers: layers.map((layer) => t(`review.layerWords.${layer}`)).join(", "),
        })}
      />
      <Stat
        label={t("review.beforePublishing")}
        value={open ? t("review.flagsLeft", { count: open }) : t("review.noneLeft")}
        tone={open ? "warn" : undefined}
        note={open ? t("review.flagsHint") : t("review.allSettledHint")}
      />
    </section>
  );
}

function Gone() {
  const { t } = useTranslation();
  return (
    <div className="rounded-[20px] bg-white p-6">
      <p className="text-base">{t("review.gone")}</p>
      <Button asChild variant="dark" size="sm" className="mt-4">
        <Link to="/policies">{t("review.backToPolicies")}</Link>
      </Button>
    </div>
  );
}

/** The clause and every clause beneath it, whose paragraphs light up together. */
function subtreeOf(clauses: readonly DraftClause[], key: string | null): Set<string> {
  const found = walk(clauses).find((clause) => clause.key === key);
  return new Set(found ? walk([found]).map((clause) => clause.key) : []);
}

/**
 * A draft under review: how the file was read, what the parser could not settle,
 * and, for a new version, what changed against the one before. Publishing waits
 * until every flag is settled.
 */
export function PolicyDraftPage() {
  const { t } = useTranslation();
  const { slug = "" } = useParams();
  const navigate = useNavigate();
  const can = usePermitted();
  const canUpload = can.has(DOCUMENTS_UPLOAD);
  const canPublish = can.has(DOCUMENTS_PUBLISH);
  const draft = useDraft(slug);
  const policies = usePolicies(canUpload || canPublish);
  const file = usePolicyFile(slug, draft.data?.version.number);
  const accept = useAcceptFlags(slug);
  const fixer = useFixClause(slug);
  const [selected, setSelected] = useState<string | null>(null);
  const [splitting, setSplitting] = useState<Splitting | null>(null);
  const [tab, setTab] = useState<Tab>("changes");
  const [dialog, setDialog] = useState<"publish" | "details" | "discard" | null>(null);
  const [rejecting, setRejecting] = useState<DraftClause | null>(null);
  const [conflict, setConflict] = useState<Conflict | null>(null);
  const columns = useRef<HTMLDivElement>(null);

  if (!canUpload && !canPublish) {
    return <Navigate to="/library" replace />;
  }
  if (draft.isPending) {
    return <Loading />;
  }
  if (draft.error instanceof ApiError && draft.error.status === 404) {
    return (
      <Panel>
        <Gone />
      </Panel>
    );
  }
  if (!draft.data) {
    return <Failed onRetry={() => void draft.refetch()} />;
  }

  const current = draft.data;
  const version = current.version;
  const summary = policies.data?.find((policy) => policy.slug === slug);
  const clauses = walk(current.clauses);
  const open = openCount(current);
  const rtl = clauses.filter((clause) => isRightToLeft(clause.lang)).length * 2 > clauses.length;
  const compared = current.previous !== null;
  const shown: Tab = compared ? tab : "file";
  const matching = current.flags.filter((flag) => flag.kind === "unmatched_key");
  const others = current.flags.filter((flag) => flag.kind !== "unmatched_key");
  const openMatching = matching.filter((flag) => !isSettled(flag)).length;
  const changes = current.changes;
  const changed =
    (changes.added ?? 0) + (changes.modified ?? 0) + (changes.moved ?? 0) + (changes.removed ?? 0);

  const openByKey = new Map<string, DraftFlag[]>();
  for (const flag of current.flags) {
    if (flag.key && !isSettled(flag)) {
      openByKey.set(flag.key, [...(openByKey.get(flag.key) ?? []), flag]);
    }
  }
  const marks: Marks = {
    lit: subtreeOf(current.clauses, selected),
    flagged: new Set(openByKey.keys()),
    flaggedParagraphs: new Set(
      current.flags
        .filter((flag) => !flag.key && !isSettled(flag) && flag.paragraph !== null)
        .map((flag) => flag.paragraph ?? -1),
    ),
  };

  function failed(error: unknown) {
    const found = conflictOf(error);
    if (found) {
      setConflict(found);
    }
  }

  function acceptFlag(flag: DraftFlag) {
    accept.mutate({ revision: current.revision, positions: [flag.position] }, { onError: failed });
  }

  function fix(edit: Edit, key: string, at?: number) {
    fixer.mutate(
      { revision: current.revision, edit, key, at },
      {
        onSuccess: (fixed) => {
          setSelected(fixed.clause);
          setSplitting(null);
        },
        onError: failed,
      },
    );
  }

  const suggested = new Map<string, Edit[]>();
  for (const flag of current.flags) {
    if (flag.suggestion && !isSettled(flag)) {
      const { key, edit } = flag.suggestion;
      suggested.set(key, [...(suggested.get(key) ?? []), edit]);
    }
  }

  /** The fix a flag suggests, on a button that names what it does. */
  function suggestion(found: FlagSuggestion) {
    const target = clauses.find((clause) => clause.key === found.key);
    const before = placeOf(current.clauses, found.key)?.before;
    let label: string;
    let icon: ReactNode;
    if (found.edit === "split") {
      const place = target?.splits?.find((split) => split.at === found.at);
      label = t("review.suggestedSplit", {
        key: isolate(shortKey(found.key, slug)),
        label: isolate(place?.label ?? ""),
      });
      icon = <ArrowLeftRight aria-hidden className="size-4" />;
    } else if (found.edit === "move-under" && before) {
      label = t("review.suggestedMoveUnder", { key: isolate(shortKey(before.key, slug)) });
      icon = <ListIndentIncrease aria-hidden className="size-4" />;
    } else if (found.edit === "make-heading") {
      label = t("review.makeHeading");
      icon = <Heading aria-hidden className="size-4" />;
    } else {
      return null;
    }
    return (
      <Button
        size="sm"
        className={small}
        disabled={fixer.isPending}
        onClick={() => {
          if (found.edit === "split") {
            setSelected(found.key);
            setSplitting({ key: found.key, at: found.at });
            setTab("file");
            columns.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
          } else {
            fix(found.edit, found.key);
          }
        }}
      >
        {icon}
        {label}
      </Button>
    );
  }

  function show(flag: DraftFlag) {
    const paragraph = file.data?.paragraphs.find((line) => line.position === flag.paragraph);
    setSelected(flag.key ?? paragraph?.clause ?? null);
    setTab("file");
    columns.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
  }

  const uploaded = formatWhen(version.created_at);
  return (
    <Panel>
      <nav aria-label={t("review.crumbs")} className="flex flex-wrap gap-1.5 text-sm text-muted">
        <Link to="/policies" className="hover:underline">
          {t("policies.title")}
        </Link>
        <span aria-hidden>›</span>
        <span dir="auto" className="text-ink-2">
          {version.title}
        </span>
      </nav>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0 flex-[1_1_520px]">
          {/* The heading lines up with the page; the title keeps its own direction. */}
          <h1 className="text-[32px] leading-tight font-semibold tracking-[-0.025em] sm:text-4xl">
            <bdi>{version.title}</bdi>
          </h1>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <span className="rounded-full bg-ink px-3 py-1.5 text-[13px] font-semibold text-white">
              {t("review.draft", { label: isolate(current.next_label) })}
            </span>
            <Chip>
              {t("review.from")} <bdi>{version.source.name}</bdi>
            </Chip>
            <Chip>{t("review.takesEffect", { date: formatDate(version.effective_date) })}</Chip>
            <span className="text-[13px] text-muted">
              {version.created_by
                ? t("review.uploaded", { when: uploaded, name: version.created_by })
                : t("review.uploadedAnon", { when: uploaded })}
            </span>
          </div>
        </div>
        <div className="flex flex-col items-start gap-1.5 sm:items-end">
          <div className="flex flex-wrap gap-2.5">
            {canUpload ? (
              <Button variant="ghost" onClick={() => setDialog("discard")}>
                {t("review.discard")}
              </Button>
            ) : null}
            {canUpload ? (
              <Button variant="quiet" onClick={() => setDialog("details")}>
                <Pencil aria-hidden className="size-4" />
                {t("review.details")}
              </Button>
            ) : null}
            {canPublish ? (
              <Button disabled={open > 0} onClick={() => setDialog("publish")}>
                {t("review.publish")}
              </Button>
            ) : null}
          </div>
          <span
            className={cn("text-[13px] font-medium", open ? "text-warn-ink" : "text-brand-dark")}
          >
            {open ? t("review.toSettle", { count: open }) : t("review.allSettled")}
          </span>
        </div>
      </div>

      {compared ? (
        <SegmentedChoice
          label={t("review.sections")}
          value={shown}
          onChange={setTab}
          options={[
            { value: "changes", label: t("review.whatChanged", { count: changed }) },
            { value: "file", label: t("review.theFile") },
          ]}
        />
      ) : null}

      {accept.error && !conflictOf(accept.error) ? (
        <Notice tone="danger">{t("common.failed")}</Notice>
      ) : null}
      {fixer.error && !conflictOf(fixer.error) ? (
        <Notice tone="danger">
          {fixer.error instanceof ApiError && fixer.error.kind === "fix-refused"
            ? t("review.fixRefused", { detail: fixer.error.problem?.detail ?? "" })
            : t("common.failed")}
        </Notice>
      ) : null}

      {shown === "changes" ? (
        <WhatChanged
          draft={current}
          summary={summary}
          canSettle={canUpload}
          busy={accept.isPending}
          onAccept={acceptFlag}
          onReject={setRejecting}
        />
      ) : (
        <>
          <Checks draft={current} />
          {current.notices.length ? (
            <Notice tone="quiet">
              <p className="font-semibold">{t("review.notices")}</p>
              {current.notices.map((notice) => (
                <p key={notice}>{notice}</p>
              ))}
            </Notice>
          ) : null}
          {others.length ? (
            <section className="rounded-[20px] bg-white p-[18px]" aria-labelledby="flags-heading">
              <h2 id="flags-heading" className="mb-3 text-lg font-semibold">
                {others.some((flag) => !isSettled(flag))
                  ? t("review.toSettleHeading")
                  : t("review.settledHeading")}
              </h2>
              <div className="grid grid-cols-[repeat(auto-fit,minmax(min(380px,100%),1fr))] gap-3">
                {others.map((flag) => (
                  <FlagCard
                    key={flag.position}
                    flag={flag}
                    slug={slug}
                    actions={
                      <>
                        {canUpload && flag.suggestion ? suggestion(flag.suggestion) : null}
                        {canUpload ? (
                          <Button
                            size="sm"
                            variant="quiet"
                            className={small}
                            disabled={accept.isPending}
                            onClick={() => acceptFlag(flag)}
                          >
                            <Check aria-hidden className="size-4" />
                            {t("review.accept")}
                          </Button>
                        ) : null}
                        {flag.key || flag.paragraph !== null ? (
                          <Button
                            size="sm"
                            variant="ghost"
                            className={small}
                            onClick={() => show(flag)}
                          >
                            {t("review.showIt")}
                          </Button>
                        ) : null}
                      </>
                    }
                  />
                ))}
              </div>
              {openMatching ? (
                <p className="mt-3 text-sm text-muted">
                  <button
                    type="button"
                    className="font-medium text-brand-dark hover:underline"
                    onClick={() => setTab("changes")}
                  >
                    {t("review.moreInChanges", { count: openMatching })}
                  </button>
                </p>
              ) : null}
            </section>
          ) : null}
          <div ref={columns} className="flex scroll-mt-4 flex-wrap items-start gap-4">
            <div className="min-w-0 flex-[1_1_440px] rounded-[20px] bg-white p-[22px]">
              <FileAsRead
                file={file.data}
                failed={file.isError}
                onRetry={() => void file.refetch()}
                slug={slug}
                number={version.number}
                selected={selected}
                marks={marks}
                rtl={rtl}
                onSelect={setSelected}
              />
            </div>
            <div className="flex min-w-0 flex-[1.15_1_480px] flex-col gap-4">
              <div className="rounded-[20px] bg-white p-[22px]">
                <ClauseTree
                  clauses={current.clauses}
                  slug={slug}
                  selected={selected}
                  flags={openByKey}
                  rtl={rtl}
                  onSelect={(key) => {
                    setSelected(key);
                    if (splitting?.key !== key) {
                      setSplitting(null);
                    }
                  }}
                  fixing={
                    canUpload
                      ? {
                          busy: fixer.isPending,
                          suggested,
                          splitting,
                          onSplitting: setSplitting,
                          onFix: fix,
                        }
                      : undefined
                  }
                />
              </div>
              {canUpload ? (
                <div className="rounded-[20px] bg-white p-[22px]">
                  <Toolbox />
                </div>
              ) : null}
            </div>
          </div>
        </>
      )}

      <PublishDialog
        open={dialog === "publish"}
        draft={current}
        summary={summary}
        onClose={() => setDialog(null)}
        onPublished={(published) => {
          const state: { published: Published } = {
            published: {
              title: published.title,
              label: published.label ?? "",
              effectiveDate: published.effective_date,
            },
          };
          void navigate("/policies", { state });
        }}
        onConflict={setConflict}
      />
      {dialog === "details" ? (
        <DetailsDialog
          open
          draft={current}
          summary={summary}
          onClose={() => setDialog(null)}
          onConflict={setConflict}
        />
      ) : null}
      <DiscardDialog
        open={dialog === "discard"}
        draft={current}
        summary={summary}
        onClose={() => setDialog(null)}
        onDiscarded={() => void navigate("/policies")}
        onConflict={setConflict}
      />
      <RejectDialog
        clause={rejecting}
        draft={current}
        onClose={() => setRejecting(null)}
        onConflict={setConflict}
      />
      <ConflictDialog
        conflict={conflict}
        onReload={() => {
          setConflict(null);
          void draft.refetch();
        }}
        onClose={() => setConflict(null)}
      />
    </Panel>
  );
}
