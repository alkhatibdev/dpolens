import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/api/client";
import {
  useDiscard,
  useEditDraft,
  usePublish,
  useRejectMatch,
  useSameRule,
  type DraftClause,
  type PolicyDraft,
  type PolicySummary,
  type PolicyVersion,
} from "@/api/policies";
import { Notice } from "@/components/Notice";
import { Button } from "@/components/ui/button";
import { Dialog, DialogActions, DialogClose, DialogContent } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { formatDate, formatWhen } from "@/lib/format";
import { conflictOf, isolate, shortKey, today, walk, type Conflict } from "@/lib/policies";
import { cn } from "@/lib/utils";

/** The version a new one must take effect after: the latest published, in force or not yet. */
function latestOf(summary: PolicySummary | undefined): { label: string; date: string } | null {
  if (summary?.scheduled) {
    return { label: summary.scheduled.label, date: summary.scheduled.effective_date };
  }
  if (summary?.in_force && summary.in_force_since) {
    return { label: summary.in_force, date: summary.in_force_since };
  }
  return null;
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-[13px] text-muted">{label}</dt>
      <dd className="mt-1 text-[15px] font-semibold">{value}</dd>
    </div>
  );
}

export function PublishDialog({
  open,
  draft,
  summary,
  onClose,
  onPublished,
  onConflict,
}: {
  open: boolean;
  draft: PolicyDraft;
  summary: PolicySummary | undefined;
  onClose: () => void;
  onPublished: (version: PolicyVersion) => void;
  onConflict: (conflict: Conflict) => void;
}) {
  const { t } = useTranslation();
  const publish = usePublish(draft.version.slug);
  const version = draft.version;
  const label = draft.next_label;
  const latest = latestOf(summary);
  const later = version.effective_date > today();
  const flags = draft.flags.length;
  const error = publish.error;

  function close() {
    publish.reset();
    onClose();
  }

  let refusal: string | null = null;
  if (error instanceof ApiError) {
    switch (error.kind) {
      case "effective-date-too-early":
        refusal = latest
          ? t("publishing.tooEarly", { label: latest.label, date: formatDate(latest.date) })
          : (error.problem?.detail ?? t("common.failed"));
        break;
      case "version-label-taken":
        refusal = t("publishing.labelTaken", { title: version.title, label });
        break;
      case "flags-open":
        refusal = t("publishing.flagsOpen", { count: error.problem?.flags?.length ?? 0 });
        break;
      default:
        refusal = t("common.failed");
    }
  } else if (error) {
    refusal = t("common.failed");
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !next && close()}>
      <DialogContent
        title={t("publishing.title", { label: isolate(label), title: isolate(version.title) })}
      >
        <dl className="grid grid-cols-[repeat(auto-fit,minmax(100px,1fr))] gap-3.5 rounded-2xl bg-panel p-4">
          <Fact label={t("publishing.takesEffect")} value={formatDate(version.effective_date)} />
          <Fact label={t("publishing.label")} value={label} />
          <Fact label={t("publishing.clauses")} value={String(walk(draft.clauses).length)} />
          <Fact
            label={t("publishing.flags")}
            value={flags ? t("publishing.flagsSettled", { count: flags }) : t("publishing.noFlags")}
          />
        </dl>
        <p className="text-[15px] leading-relaxed text-ink-2">
          {later
            ? t("publishing.later", { date: formatDate(version.effective_date) })
            : t("publishing.now")}
          {later && summary?.in_force
            ? ` ${t("publishing.laterUntil", { current: summary.in_force })}`
            : null}
        </p>
        <p className="text-[15px] leading-relaxed text-ink-2">
          {t("publishing.never")}
          {draft.previous
            ? ` ${t("publishing.citations", { previous: draft.previous, label })}`
            : null}
        </p>
        {refusal ? <Notice tone="danger">{refusal}</Notice> : null}
        <DialogActions>
          <Button
            disabled={publish.isPending}
            onClick={() =>
              publish.mutate(
                { revision: draft.revision },
                {
                  onSuccess: (published) => {
                    publish.reset();
                    onPublished(published);
                  },
                  onError: (failure) => {
                    const conflict = conflictOf(failure);
                    if (conflict) {
                      close();
                      onConflict(conflict);
                    }
                  },
                },
              )
            }
          >
            {t("publishing.submit", { label: isolate(label) })}
          </Button>
          <DialogClose asChild>
            <Button variant="ghost">{t("common.cancel")}</Button>
          </DialogClose>
        </DialogActions>
      </DialogContent>
    </Dialog>
  );
}

export function DetailsDialog({
  open,
  draft,
  summary,
  onClose,
  onConflict,
}: {
  open: boolean;
  draft: PolicyDraft;
  summary: PolicySummary | undefined;
  onClose: () => void;
  onConflict: (conflict: Conflict) => void;
}) {
  const { t } = useTranslation();
  const edit = useEditDraft(draft.version.slug);
  const version = draft.version;
  const [title, setTitle] = useState(version.title);
  const [effective, setEffective] = useState(version.effective_date);
  const [label, setLabel] = useState(version.label ?? "");
  const latest = latestOf(summary);
  const tooEarly = latest !== null && effective !== "" && effective <= latest.date;

  function close() {
    edit.reset();
    onClose();
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (tooEarly || !effective) {
      return;
    }
    edit.mutate(
      {
        revision: draft.revision,
        title: title.trim() || undefined,
        effective_date: effective,
        version_label: label.trim(),
      },
      {
        onSuccess: close,
        onError: (failure) => {
          const conflict = conflictOf(failure);
          if (conflict) {
            close();
            onConflict(conflict);
          }
        },
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !next && close()}>
      <DialogContent
        title={t("publishing.detailsTitle")}
        className="w-[min(480px,calc(100vw-24px))]"
      >
        <form onSubmit={submit} className="flex flex-col gap-5" noValidate>
          <div className="flex flex-col gap-2">
            <Label htmlFor="draft-title">{t("publishing.titleLabel")}</Label>
            <Input
              id="draft-title"
              value={title}
              maxLength={300}
              onChange={(event) => setTitle(event.target.value)}
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="draft-date">{t("publishing.effective")}</Label>
            <Input
              id="draft-date"
              type="date"
              required
              value={effective}
              aria-invalid={tooEarly || undefined}
              aria-describedby={tooEarly ? "draft-date-error" : undefined}
              onChange={(event) => setEffective(event.target.value)}
            />
            {tooEarly && latest ? (
              <p id="draft-date-error" className="text-[13px] leading-normal text-danger-ink">
                {t("publishing.tooEarly", { label: latest.label, date: formatDate(latest.date) })}
              </p>
            ) : null}
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="draft-label">{t("publishing.labelLabel")}</Label>
            <Input
              id="draft-label"
              value={label}
              maxLength={100}
              placeholder={draft.next_label}
              aria-describedby="draft-label-hint"
              onChange={(event) => setLabel(event.target.value)}
            />
            <p id="draft-label-hint" className="text-[13px] text-muted">
              {t("publishing.labelHint")}
            </p>
          </div>
          {edit.error && !conflictOf(edit.error) ? (
            <Notice tone="danger">{t("common.failed")}</Notice>
          ) : null}
          <DialogActions>
            <Button type="submit" disabled={edit.isPending || tooEarly}>
              {t("common.save")}
            </Button>
            <DialogClose asChild>
              <Button type="button" variant="ghost">
                {t("common.cancel")}
              </Button>
            </DialogClose>
          </DialogActions>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function DiscardDialog({
  open,
  draft,
  summary,
  onClose,
  onDiscarded,
  onConflict,
}: {
  open: boolean;
  draft: PolicyDraft;
  summary: PolicySummary | undefined;
  onClose: () => void;
  onDiscarded: () => void;
  onConflict: (conflict: Conflict) => void;
}) {
  const { t } = useTranslation();
  const discard = useDiscard(draft.version.slug);

  function close() {
    discard.reset();
    onClose();
  }

  const body = t("review.discardBody", { label: isolate(draft.next_label) });
  return (
    <Dialog open={open} onOpenChange={(next) => !next && close()}>
      <DialogContent
        title={t("review.discardTitle", { title: isolate(draft.version.title) })}
        description={
          summary?.in_force
            ? `${body} ${t("review.discardInForce", { label: summary.in_force })}`
            : body
        }
      >
        {discard.error && !conflictOf(discard.error) ? (
          <Notice tone="danger">{t("common.failed")}</Notice>
        ) : null}
        <DialogActions>
          <Button
            variant="danger"
            size="sm"
            disabled={discard.isPending}
            onClick={() =>
              discard.mutate(
                { revision: draft.revision },
                {
                  onSuccess: onDiscarded,
                  onError: (failure) => {
                    const conflict = conflictOf(failure);
                    if (conflict) {
                      close();
                      onConflict(conflict);
                    }
                  },
                },
              )
            }
          >
            {t("review.discardSubmit")}
          </Button>
          <DialogClose asChild>
            <Button variant="ghost" size="sm">
              {t("common.cancel")}
            </Button>
          </DialogClose>
        </DialogActions>
      </DialogContent>
    </Dialog>
  );
}

/** Asked once, because only a new upload undoes it. */
export function RejectDialog({
  clause,
  draft,
  onClose,
  onConflict,
}: {
  clause: DraftClause | null;
  draft: PolicyDraft;
  onClose: () => void;
  onConflict: (conflict: Conflict) => void;
}) {
  const { t } = useTranslation();
  const reject = useRejectMatch(draft.version.slug);
  if (!clause) {
    return null;
  }
  const slug = draft.version.slug;
  const key = shortKey(clause.key, slug);

  function close() {
    reject.reset();
    onClose();
  }

  return (
    <Dialog open onOpenChange={(next) => !next && close()}>
      <DialogContent
        title={t("changes.rejectTitle", { key: isolate(key) })}
        description={t("changes.rejectBody", {
          key: isolate(key),
          previous: isolate(draft.previous ?? ""),
          earlier: isolate(shortKey(clause.continues ?? "", slug)),
        })}
      >
        {reject.error && !conflictOf(reject.error) ? (
          <Notice tone="danger">{t("common.failed")}</Notice>
        ) : null}
        <DialogActions>
          <Button
            variant="dark"
            size="sm"
            disabled={reject.isPending}
            onClick={() =>
              reject.mutate(
                { revision: draft.revision, key: clause.key },
                {
                  onSuccess: close,
                  onError: (failure) => {
                    const conflict = conflictOf(failure);
                    if (conflict) {
                      close();
                      onConflict(conflict);
                    }
                  },
                },
              )
            }
          >
            {t("changes.differentRule")}
          </Button>
          <DialogClose asChild>
            <Button variant="ghost" size="sm">
              {t("common.cancel")}
            </Button>
          </DialogClose>
        </DialogActions>
      </DialogContent>
    </Dialog>
  );
}

/**
 * Which clause of the version before a new clause continues, when no flag asks: the clauses
 * nothing continues, closest first, and what saying so does to citations.
 */
export function SameRuleDialog({
  clause,
  draft,
  onClose,
  onConflict,
}: {
  clause: DraftClause | null;
  draft: PolicyDraft;
  onClose: () => void;
  onConflict: (conflict: Conflict) => void;
}) {
  const { t } = useTranslation();
  const same = useSameRule(draft.version.slug);
  const [chosen, setChosen] = useState<string | null>(null);
  if (!clause) {
    return null;
  }
  const slug = draft.version.slug;
  const key = shortKey(clause.key, slug);
  const previous = draft.previous ?? "";
  const removed = new Map(draft.removed.map((gone) => [gone.key, gone]));
  const candidates = clause.candidates ?? [];
  const choice = chosen ?? candidates[0]?.key ?? null;
  const picked = choice ? removed.get(choice) : undefined;
  const earlier = isolate(shortKey(choice ?? "", slug));
  const renumbered = picked !== undefined && shortKey(picked.key, slug) !== key;
  const reworded =
    picked !== undefined &&
    (picked.text !== clause.text || (picked.heading ?? null) !== (clause.heading ?? null));
  const how = renumbered
    ? reworded
      ? "renumberedReworded"
      : "renumbered"
    : reworded
      ? "reworded"
      : "same";
  const refused =
    same.error instanceof ApiError && same.error.kind === "match-refused"
      ? (same.error.problem?.detail ?? "")
      : null;

  function close() {
    same.reset();
    setChosen(null);
    onClose();
  }

  return (
    <Dialog open onOpenChange={(next) => !next && close()}>
      <DialogContent
        className="w-[min(600px,calc(100vw-24px))]"
        title={t("changes.chooseTitle", { label: isolate(previous), key: isolate(key) })}
      >
        <div className="flex gap-3 rounded-[14px] bg-panel px-3.5 py-3">
          <span className="font-mono text-[13px] leading-relaxed font-medium whitespace-nowrap text-brand-dark">
            {key}
          </span>
          <p dir="auto" className="min-w-0 text-sm leading-relaxed text-ink-2">
            {clause.heading ? <span className="font-semibold">{clause.heading} </span> : null}
            {clause.text}
          </p>
        </div>
        <p className="text-[15px] leading-relaxed text-ink-2">
          {t("changes.chooseIntro", { label: isolate(previous) })}
        </p>
        <fieldset className="flex flex-col gap-2.5">
          <legend className="sr-only">
            {t("changes.chooseTitle", { label: isolate(previous), key: isolate(key) })}
          </legend>
          {candidates.map((candidate) => {
            const gone = removed.get(candidate.key);
            const selected = candidate.key === choice;
            return (
              <label
                key={candidate.key}
                className={cn(
                  "flex cursor-pointer items-start gap-3 rounded-[14px] has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-ink",
                  selected
                    ? "border-2 border-brand-dark bg-brand-soft px-[13px] py-[11px]"
                    : "border border-line px-3.5 py-3",
                )}
              >
                <input
                  type="radio"
                  name="continues"
                  value={candidate.key}
                  checked={selected}
                  onChange={() => setChosen(candidate.key)}
                  className="sr-only"
                />
                <span
                  aria-hidden
                  className="mt-0.5 inline-flex size-[18px] shrink-0 items-center justify-center rounded-full border-2 border-brand-dark"
                >
                  {selected ? <span className="size-2 rounded-full bg-brand-dark" /> : null}
                </span>
                <span className="flex min-w-0 flex-col gap-1">
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-[13px] font-medium text-brand-dark">
                      {shortKey(candidate.key, slug)}
                    </span>
                    <span className="text-xs text-muted">
                      {t(`changes.closeness.${candidate.closeness}`)}
                    </span>
                  </span>
                  <span dir="auto" className="text-sm leading-relaxed text-ink-2">
                    {gone?.heading ? <span className="font-semibold">{gone.heading} </span> : null}
                    {gone?.text}
                  </span>
                </span>
              </label>
            );
          })}
        </fieldset>
        {choice ? (
          <p className="text-[15px] leading-relaxed text-ink-2">
            {t("changes.chooseEffect", {
              key: isolate(key),
              label: isolate(previous),
              earlier,
              how: t(`changes.how.${how}`),
            })}
          </p>
        ) : null}
        {refused !== null ? <Notice tone="danger">{refused}</Notice> : null}
        {same.error && refused === null && !conflictOf(same.error) ? (
          <Notice tone="danger">{t("common.failed")}</Notice>
        ) : null}
        <DialogActions>
          <Button
            disabled={same.isPending || !choice}
            onClick={() =>
              choice &&
              same.mutate(
                { revision: draft.revision, key: clause.key, continues: choice },
                {
                  onSuccess: close,
                  onError: (failure) => {
                    const conflict = conflictOf(failure);
                    if (conflict) {
                      close();
                      onConflict(conflict);
                    }
                  },
                },
              )
            }
          >
            {t("changes.sameAs", { key: earlier })}
          </Button>
          <DialogClose asChild>
            <Button variant="ghost">{t("common.cancel")}</Button>
          </DialogClose>
        </DialogActions>
      </DialogContent>
    </Dialog>
  );
}

/** Somebody changed the draft after it was opened, so the change just made was not saved. */
export function ConflictDialog({
  conflict,
  onReload,
  onClose,
}: {
  conflict: Conflict | null;
  onReload: () => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  if (!conflict) {
    return null;
  }
  return (
    <Dialog open onOpenChange={(next) => !next && onClose()}>
      <DialogContent
        title={
          conflict.by
            ? t("review.conflictTitle", { name: conflict.by })
            : t("review.conflictTitleAnon")
        }
        description={t("review.conflictBody", { when: conflict.at ? formatWhen(conflict.at) : "" })}
      >
        <DialogActions>
          <Button size="sm" onClick={onReload}>
            {t("review.reload")}
          </Button>
          <DialogClose asChild>
            <Button variant="ghost" size="sm">
              {t("common.close")}
            </Button>
          </DialogClose>
        </DialogActions>
      </DialogContent>
    </Dialog>
  );
}
