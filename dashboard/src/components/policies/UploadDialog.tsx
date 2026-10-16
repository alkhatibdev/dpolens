import { FileText, Upload } from "lucide-react";
import { useId, useRef, useState, type DragEvent, type FormEvent, type ReactNode } from "react";
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";

import { ApiError } from "@/api/client";
import { useUpload, type PolicySummary } from "@/api/policies";
import { Notice } from "@/components/Notice";
import { Button } from "@/components/ui/button";
import { Dialog, DialogActions, DialogClose, DialogContent } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { formatDate, formatWhen } from "@/lib/format";
import { PREFIX, formatSize, isolate, isWord, prefixFrom, refusalFor, today } from "@/lib/policies";
import { cn } from "@/lib/utils";

/** A labelled field with the line under it that says what it is for, or what is wrong. */
function Field({
  id,
  label,
  hint,
  error,
  children,
}: {
  id: string;
  label: string;
  hint: ReactNode;
  error?: string | null;
  children: ReactNode;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-2">
      <Label htmlFor={id}>{label}</Label>
      {children}
      <p
        id={`${id}-hint`}
        className={cn("text-[13px] leading-normal", error ? "text-danger-ink" : "text-muted")}
      >
        {error ?? hint}
      </p>
    </div>
  );
}

/** The dashboard's own words for a refused upload. A file the reader could not read says why. */
function refusalOf(
  t: TFunction,
  error: unknown,
  prefix: string,
  policies: readonly PolicySummary[],
): string | null {
  if (!(error instanceof ApiError)) {
    return error ? t("common.failed") : null;
  }
  switch (error.kind) {
    case "unreadable-policy":
      return error.problem?.detail ?? t("common.failed");
    case "too-large":
      return t("upload.refused.tooLarge");
    case "policy-exists":
      return policies.some((policy) => policy.slug === prefix)
        ? t("upload.refused.prefixTaken", { prefix })
        : t("upload.refused.prefixTakenByLaw", { prefix });
    case "bad-slug":
      return t("upload.refused.badPrefix");
    case "draft-exists":
      return t("upload.refused.draftExists", { number: error.problem?.version ?? "" });
    default:
      return t("common.failed");
  }
}

/**
 * Upload a policy, or a new version of one. The file is read at once and becomes
 * a draft, which opens for review; a file that cannot be read is refused here.
 */
export function UploadDialog({
  open,
  policy,
  policies,
  onClose,
}: {
  open: boolean;
  /** The policy a new version is for, or null for a new policy. */
  policy: PolicySummary | null;
  policies: readonly PolicySummary[];
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const upload = useUpload();
  const ids = useId();
  const picker = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [prefix, setPrefix] = useState("");
  const [prefixTouched, setPrefixTouched] = useState(false);
  const [effective, setEffective] = useState(today());
  const [label, setLabel] = useState("");
  const [checked, setChecked] = useState(false);

  function reset() {
    setFile(null);
    setTitle("");
    setPrefix("");
    setPrefixTouched(false);
    setEffective(today());
    setLabel("");
    setChecked(false);
    upload.reset();
  }

  function choose(chosen: File | undefined) {
    if (!chosen) {
      return;
    }
    upload.reset();
    setFile(chosen);
    if (!prefixTouched) {
      setPrefix(prefixFrom(chosen.name));
    }
  }

  function dropped(event: DragEvent) {
    event.preventDefault();
    choose(event.dataTransfer.files[0]);
  }

  const before = file ? refusalFor(file) : null;
  const prefixProblem =
    policy || !checked
      ? null
      : !prefix
        ? t("upload.refused.noPrefix")
        : PREFIX.test(prefix)
          ? null
          : t("upload.refused.badPrefix");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setChecked(true);
    if (!file || before || (!policy && !PREFIX.test(prefix))) {
      return;
    }
    try {
      const draft = await upload.mutateAsync({
        file,
        of: policy?.slug,
        slug: policy ? undefined : prefix,
        title: title.trim(),
        effectiveDate: effective,
        label: label.trim(),
        replace: policy?.draft != null,
      });
      reset();
      onClose();
      void navigate(`/policies/${draft.version.slug}/draft`);
    } catch {
      // Said below the file.
    }
  }

  const refused = before
    ? t(`upload.refused.${before}`)
    : refusalOf(t, upload.error, prefix, policies);
  const since = policy?.scheduled?.effective_date ?? policy?.in_force_since ?? null;
  const sinceLabel = policy?.scheduled?.label ?? policy?.in_force ?? null;
  const effectiveHint =
    policy && since && sinceLabel
      ? t(policy.scheduled ? "upload.effectiveAfterLater" : "upload.effectiveAfter", {
          date: formatDate(since),
          label: sinceLabel,
        })
      : t("upload.effectiveHint");
  const replacing = policy?.draft != null;
  // A new version is matched with the latest published, which may not be in force yet.
  const matchedWith = policy ? (policy.scheduled?.label ?? policy.in_force) : null;
  const review = policy?.review;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          reset();
          onClose();
        }
      }}
    >
      <DialogContent
        title={
          policy ? t("upload.versionTitle", { title: isolate(policy.title) }) : t("upload.title")
        }
        className="w-[min(600px,calc(100vw-24px))]"
      >
        <form onSubmit={(event) => void submit(event)} className="flex flex-col gap-5" noValidate>
          <input
            ref={picker}
            id={`${ids}-file`}
            type="file"
            accept=".docx,.md,.markdown"
            className="sr-only"
            onChange={(event) => {
              choose(event.target.files?.[0]);
              event.target.value = "";
            }}
          />
          {file ? (
            <div className="flex flex-col gap-2.5">
              <div
                onDragOver={(event) => event.preventDefault()}
                onDrop={dropped}
                className={cn(
                  "flex items-center gap-3 rounded-2xl border bg-white px-3.5 py-3",
                  refused ? "border-[1.5px] border-danger-soft" : "border-line",
                )}
              >
                <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-field">
                  <FileText aria-hidden className="size-5 text-ink-2" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-[15px] font-semibold break-words">{file.name}</span>
                  <span className="text-[13px] text-muted">
                    {t(isWord(file.name) ? "upload.word" : "upload.markdown", {
                      size: formatSize(file.size),
                    })}
                  </span>
                </span>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="text-brand-dark"
                  onClick={() => picker.current?.click()}
                >
                  {t("upload.another")}
                </Button>
              </div>
              {refused ? <Notice tone="danger">{refused}</Notice> : null}
            </div>
          ) : (
            <label
              htmlFor={`${ids}-file`}
              onDragOver={(event) => event.preventDefault()}
              onDrop={dropped}
              className="flex cursor-pointer flex-col items-center gap-2.5 rounded-[18px] border-2 border-dashed border-line-strong bg-panel px-5 py-8 text-center hover:bg-field focus-within:border-brand"
            >
              <span className="grid size-13 place-items-center rounded-full bg-brand-soft">
                <Upload aria-hidden className="size-6 text-brand-dark" />
              </span>
              <span className="text-base font-semibold">{t("upload.drop")}</span>
              <span className="max-w-[40ch] text-sm leading-relaxed text-muted">
                {t("upload.dropHint")}
              </span>
            </label>
          )}

          {replacing && review ? (
            <Notice tone="warn">
              {review.uploaded_by
                ? t("upload.draftOpen", {
                    label: isolate(review.next_label),
                    name: review.uploaded_by,
                    when: formatWhen(review.uploaded_at),
                  })
                : t("upload.draftOpenAnon", {
                    label: isolate(review.next_label),
                    when: formatWhen(review.uploaded_at),
                  })}
            </Notice>
          ) : null}

          {policy ? null : (
            <>
              <Field
                id={`${ids}-title`}
                label={t("upload.titleLabel")}
                hint={t("upload.titleHint")}
              >
                <Input
                  id={`${ids}-title`}
                  value={title}
                  maxLength={300}
                  placeholder={t("upload.titlePlaceholder")}
                  aria-describedby={`${ids}-title-hint`}
                  onChange={(event) => setTitle(event.target.value)}
                />
              </Field>
              <Field
                id={`${ids}-prefix`}
                label={t("upload.prefix")}
                hint={t("upload.prefixHint", { example: `${prefix || "data-protection"}:3.2` })}
                error={prefixProblem}
              >
                <Input
                  id={`${ids}-prefix`}
                  value={prefix}
                  maxLength={60}
                  className="font-mono text-[15px]"
                  aria-describedby={`${ids}-prefix-hint`}
                  aria-invalid={prefixProblem ? true : undefined}
                  onChange={(event) => {
                    setPrefixTouched(true);
                    setPrefix(event.target.value.trim().toLowerCase());
                  }}
                />
              </Field>
            </>
          )}

          <div className="flex flex-wrap gap-3.5">
            <div className="min-w-0 flex-[1_1_200px]">
              <Field id={`${ids}-date`} label={t("upload.effective")} hint={effectiveHint}>
                <Input
                  id={`${ids}-date`}
                  type="date"
                  required
                  value={effective}
                  aria-describedby={`${ids}-date-hint`}
                  onChange={(event) => setEffective(event.target.value)}
                />
              </Field>
            </div>
            <div className="min-w-0 flex-[1_1_140px]">
              <Field id={`${ids}-label`} label={t("upload.label")} hint={t("upload.labelHint")}>
                <Input
                  id={`${ids}-label`}
                  value={label}
                  maxLength={100}
                  placeholder={policy?.next_label ?? "1"}
                  aria-describedby={`${ids}-label-hint`}
                  onChange={(event) => setLabel(event.target.value)}
                />
              </Field>
            </div>
          </div>

          <DialogActions>
            <Button type="submit" disabled={!file || upload.isPending}>
              {upload.isPending
                ? t("upload.working")
                : replacing
                  ? t("upload.replace")
                  : t("upload.submit")}
            </Button>
            <DialogClose asChild>
              <Button type="button" variant="ghost">
                {t("common.cancel")}
              </Button>
            </DialogClose>
            <span className="min-w-0 flex-[1_1_200px] text-[13px] leading-normal text-muted">
              {matchedWith
                ? t("upload.versionNote", { label: matchedWith })
                : policy
                  ? null
                  : t("upload.newNote")}
            </span>
          </DialogActions>
        </form>
      </DialogContent>
    </Dialog>
  );
}
