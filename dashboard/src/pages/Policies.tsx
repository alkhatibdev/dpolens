import { Archive, BookOpen, CircleCheck, Download, Ellipsis, Upload } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, Navigate, useLocation, useNavigate } from "react-router";

import { useArchive, usePolicies, type PolicySummary } from "@/api/policies";
import { FilterButton, FindBox } from "@/components/Filters";
import { Notice } from "@/components/Notice";
import { PageHeading, TableCard, td, th } from "@/components/Page";
import { UploadDialog } from "@/components/policies/UploadDialog";
import { Chip, Failed, Loading, Panel } from "@/components/States";
import { Button } from "@/components/ui/button";
import { Dialog, DialogActions, DialogClose, DialogContent } from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { download } from "@/lib/download";
import { formatDate, formatDay } from "@/lib/format";
import { DOCUMENTS_PUBLISH, DOCUMENTS_READ, DOCUMENTS_UPLOAD } from "@/lib/permissions";
import { isolate, today } from "@/lib/policies";
import { cn } from "@/lib/utils";
import { usePermitted } from "@/session";

type Filter = "all" | "inForce" | "drafts" | "archived";

/** What the page says after a version is published, carried from the review. */
export interface Published {
  title: string;
  label: string;
  effectiveDate: string;
}

function shows(policy: PolicySummary, filter: Filter, query: string): boolean {
  const wanted = query.trim().toLowerCase();
  if (wanted && !policy.title.toLowerCase().includes(wanted) && !policy.slug.includes(wanted)) {
    return false;
  }
  switch (filter) {
    case "inForce":
      return policy.status === "active" && policy.in_force !== null;
    case "drafts":
      return policy.draft !== null;
    case "archived":
      return policy.status === "archived";
    default:
      return true;
  }
}

/** Policies in use first, then those archived, each in the order of their titles. */
function inOrder(policies: readonly PolicySummary[]): PolicySummary[] {
  return [...policies].sort(
    (a, b) =>
      Number(a.status === "archived") - Number(b.status === "archived") ||
      a.title.localeCompare(b.title),
  );
}

function PublishedNotice({ published }: { published: Published }) {
  const { t } = useTranslation();
  const later = published.effectiveDate > today();
  return (
    <div role="status" className="flex items-start gap-3.5 rounded-[20px] bg-white p-5">
      <span className="grid size-10 shrink-0 place-items-center rounded-full bg-brand-soft">
        <CircleCheck aria-hidden className="size-5 text-brand-dark" />
      </span>
      <div>
        <p className="text-base font-semibold">
          {t("policies.published", { label: published.label, title: published.title })}
        </p>
        <p className="mt-1 text-sm leading-relaxed text-ink-2">
          {later
            ? t("policies.publishedLater", { date: formatDate(published.effectiveDate) })
            : t("policies.publishedNow")}
        </p>
      </div>
    </div>
  );
}

function InForce({ policy }: { policy: PolicySummary }) {
  const { t } = useTranslation();
  if (policy.status === "archived") {
    return <Chip tone="quiet">{t("policies.archivedChip")}</Chip>;
  }
  if (!policy.in_force || !policy.in_force_since) {
    return <span className="text-sm text-muted">{t("policies.notPublished")}</span>;
  }
  return (
    <>
      <div className="font-semibold">{t("policies.version", { label: policy.in_force })}</div>
      <div className="text-[13px] text-muted">
        {t("policies.since", { date: formatDate(policy.in_force_since, "short") })}
      </div>
    </>
  );
}

function Draft({ policy }: { policy: PolicySummary }) {
  const { t } = useTranslation();
  const scheduled = policy.scheduled ? (
    <Chip tone="quiet">
      {t("policies.scheduled", {
        label: policy.scheduled.label,
        date: formatDate(policy.scheduled.effective_date, "short"),
      })}
    </Chip>
  ) : null;
  if (policy.draft === null || !policy.review) {
    return scheduled ?? <span className="text-sm text-muted">{t("policies.none")}</span>;
  }
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="font-semibold">
        {t("policies.version", { label: isolate(policy.review.next_label) })}
      </span>
      {policy.review.open ? (
        <Chip tone="warn">{t("policies.flagsToSettle", { count: policy.review.open })}</Chip>
      ) : (
        <Chip tone="soft">{t("policies.readyToPublish")}</Chip>
      )}
      {scheduled}
    </div>
  );
}

function PolicyRow({
  policy,
  onUpload,
  onArchive,
}: {
  policy: PolicySummary;
  onUpload: () => void;
  onArchive: () => void;
}) {
  const { t } = useTranslation();
  const can = usePermitted();
  const navigate = useNavigate();
  const archived = policy.status === "archived";
  const readable = can.has(DOCUMENTS_READ);
  const inLibrary = !archived && policy.in_force !== null && readable;
  const original = policy.in_force_number;
  const items = [
    can.has(DOCUMENTS_UPLOAD) ? (
      <DropdownMenuItem key="upload" onSelect={onUpload}>
        <Upload aria-hidden />
        {t("policies.uploadVersion")}
      </DropdownMenuItem>
    ) : null,
    original !== null && readable ? (
      <DropdownMenuItem
        key="download"
        onSelect={() => void download(`/v1/policies/${policy.slug}/versions/${original}/original`)}
      >
        <Download aria-hidden />
        {t("policies.downloadOriginal")}
      </DropdownMenuItem>
    ) : null,
    inLibrary ? (
      <DropdownMenuItem key="library" onSelect={() => void navigate(`/library/${policy.slug}`)}>
        <BookOpen aria-hidden />
        {t("policies.readInLibrary")}
      </DropdownMenuItem>
    ) : null,
    !archived && can.has(DOCUMENTS_PUBLISH) ? (
      <DropdownMenuItem
        key="archive"
        onSelect={onArchive}
        className="text-danger-ink [&_svg]:text-danger-ink"
      >
        <Archive aria-hidden />
        {t("policies.archive")}
      </DropdownMenuItem>
    ) : null,
  ].filter(Boolean);
  const review = policy.review;
  const change = policy.last_change;

  return (
    <tr className={cn(archived && "opacity-70")}>
      <td className={td}>
        <div className="min-w-0">
          {inLibrary ? (
            <Link to={`/library/${policy.slug}`} className="font-semibold hover:underline">
              {policy.title}
            </Link>
          ) : (
            <span className="font-semibold">{policy.title}</span>
          )}
          <div className="mt-0.5 font-mono text-xs text-muted">{policy.slug}</div>
          {policy.sample ? (
            <div className="mt-1 text-[13px] text-muted">{t("policies.sample")}</div>
          ) : null}
        </div>
      </td>
      <td className={td}>
        <InForce policy={policy} />
      </td>
      <td className={td}>
        <Draft policy={policy} />
      </td>
      <td className={td}>
        {change ? (
          <>
            <div className="text-sm">{change.by ?? t("policies.commandLine")}</div>
            <div className="text-[13px] whitespace-nowrap text-muted">{formatDay(change.at)}</div>
          </>
        ) : null}
      </td>
      <td className={`${td} py-2.5`}>
        <div className="flex items-center justify-end gap-1.5">
          {review ? (
            <Button
              asChild
              size="sm"
              variant={review.open ? "primary" : "quiet"}
              className="h-10 rounded-[10px] px-3 text-[13px]"
            >
              <Link to={`/policies/${policy.slug}/draft`}>
                {review.open ? t("policies.continueReview") : t("policies.openDraft")}
              </Link>
            </Button>
          ) : null}
          {items.length ? (
            <DropdownMenu>
              <DropdownMenuTrigger
                aria-label={t("policies.more", { title: policy.title })}
                className="grid size-10 place-items-center rounded-full text-ink-2 hover:bg-field data-[state=open]:bg-field"
              >
                <Ellipsis aria-hidden className="size-5" />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">{items}</DropdownMenuContent>
            </DropdownMenu>
          ) : null}
        </div>
      </td>
    </tr>
  );
}

function ArchiveDialog({ policy, onClose }: { policy: PolicySummary | null; onClose: () => void }) {
  const { t } = useTranslation();
  const archive = useArchive();
  if (!policy) {
    return null;
  }
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) {
          archive.reset();
          onClose();
        }
      }}
    >
      <DialogContent
        title={t("policies.archiveTitle", { title: isolate(policy.title) })}
        description={
          policy.draft !== null
            ? `${t("policies.archiveBody")} ${t("policies.archiveDraft")}`
            : t("policies.archiveBody")
        }
      >
        {archive.error ? <Notice tone="danger">{t("common.failed")}</Notice> : null}
        <DialogActions>
          <Button
            variant="danger"
            size="sm"
            disabled={archive.isPending}
            onClick={() =>
              archive.mutate(policy.slug, {
                onSuccess: () => {
                  archive.reset();
                  onClose();
                },
              })
            }
          >
            {t("policies.archiveSubmit")}
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

export function PoliciesPage() {
  const { t } = useTranslation();
  const can = usePermitted();
  const location = useLocation();
  const reviewer = can.has(DOCUMENTS_UPLOAD) || can.has(DOCUMENTS_PUBLISH);
  const policies = usePolicies(reviewer);
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [uploading, setUploading] = useState<{ policy: PolicySummary | null } | null>(null);
  const [archiving, setArchiving] = useState<PolicySummary | null>(null);

  if (!reviewer) {
    return <Navigate to="/library" replace />;
  }

  const published = (location.state as { published?: Published } | null)?.published;
  const everything = inOrder(policies.data ?? []);
  const shown = everything.filter((policy) => shows(policy, filter, query));
  const count = (wanted: Filter) => everything.filter((policy) => shows(policy, wanted, "")).length;

  return (
    <Panel>
      <PageHeading
        title={t("policies.title")}
        subtitle={t("policies.subtitle")}
        action={
          can.has(DOCUMENTS_UPLOAD) ? (
            <Button onClick={() => setUploading({ policy: null })}>
              <Upload aria-hidden className="size-4" />
              {t("policies.upload")}
            </Button>
          ) : null
        }
      />
      {published ? <PublishedNotice published={published} /> : null}

      {policies.isPending ? <Loading /> : null}
      {policies.error ? <Failed onRetry={() => void policies.refetch()} /> : null}
      {policies.data && everything.length === 0 ? (
        <div className="rounded-[20px] bg-white p-6 text-base leading-relaxed">
          {t("policies.empty")}
        </div>
      ) : null}
      {policies.data && everything.length > 0 ? (
        <>
          <div
            className="flex flex-wrap items-center gap-2"
            role="group"
            aria-label={t("policies.filters")}
          >
            {(["all", "inForce", "drafts", "archived"] as const).map((value) => (
              <FilterButton key={value} pressed={filter === value} onClick={() => setFilter(value)}>
                {t(`policies.${value}`, { count: count(value) })}
              </FilterButton>
            ))}
            <span className="hidden flex-1 sm:block" />
            <FindBox label={t("policies.find")} value={query} onChange={setQuery} />
          </div>
          <TableCard>
            <table className="w-full min-w-[920px] border-collapse">
              <thead>
                <tr>
                  <th scope="col" className={th}>
                    {t("policies.policy")}
                  </th>
                  <th scope="col" className={th}>
                    {t("policies.inForceColumn")}
                  </th>
                  <th scope="col" className={th}>
                    {t("policies.draftColumn")}
                  </th>
                  <th scope="col" className={th}>
                    {t("policies.lastChange")}
                  </th>
                  <th scope="col" className={`${th} text-end`}>
                    {t("policies.next")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {shown.map((policy) => (
                  <PolicyRow
                    key={policy.slug}
                    policy={policy}
                    onUpload={() => setUploading({ policy })}
                    onArchive={() => setArchiving(policy)}
                  />
                ))}
              </tbody>
            </table>
            {shown.length === 0 ? (
              <p className="px-4 py-5 text-muted">{t("policies.noMatch")}</p>
            ) : null}
          </TableCard>
        </>
      ) : null}
      <p className="text-sm leading-relaxed text-muted">{t("policies.note")}</p>

      <UploadDialog
        open={uploading !== null}
        policy={uploading?.policy ?? null}
        policies={everything}
        onClose={() => setUploading(null)}
      />
      <ArchiveDialog policy={archiving} onClose={() => setArchiving(null)} />
    </Panel>
  );
}
