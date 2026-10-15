import { useQueryClient } from "@tanstack/react-query";
import { ChevronRight, Pencil, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router";

import { ApiError, api, unwrap, type Role } from "@/api/client";
import { useDeleteRole, useEditRole, usePermissions, useRole } from "@/api/roles";
import { Avatar } from "@/components/Avatar";
import { Notice } from "@/components/Notice";
import { PageHeading } from "@/components/Page";
import { holdersSummary } from "@/components/roles/holders";
import { RenameDialog } from "@/components/roles/RenameDialog";
import { Chip, Failed, Loading, Missing, Panel } from "@/components/States";
import { Button } from "@/components/ui/button";
import { Dialog, DialogActions, DialogClose, DialogContent } from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import { formatMoment, formatWhen } from "@/lib/format";
import { wordsFor } from "@/lib/permissionWords";
import {
  KNOWN_PERMISSIONS,
  PERMISSION_GROUPS,
  ROLES_MANAGE,
  USERS_MANAGE,
} from "@/lib/permissions";
import { cn } from "@/lib/utils";
import { usePermitted } from "@/session";

interface Conflict {
  latest: Role;
  by: string | null;
  at: string;
}

/** What changed from one set to another, as "turned on" and "turned off". */
function difference(from: ReadonlySet<string>, to: ReadonlySet<string>) {
  return {
    on: [...to].filter((key) => !from.has(key)).sort(),
    off: [...from].filter((key) => !to.has(key)).sort(),
  };
}

export function RolePage() {
  const { t } = useTranslation();
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const client = useQueryClient();
  const can = usePermitted();
  const role = useRole(id);
  const catalog = usePermissions();
  const edit = useEditRole();
  const remove = useDeleteRole();
  // What the person is editing from, and what they have switched since. Both stay
  // through a conflict, so their own change can be put on top of the newer version.
  const [base, setBase] = useState<Role | null>(null);
  const [draft, setDraft] = useState<Set<string> | null>(null);
  const [conflict, setConflict] = useState<Conflict | null>(null);
  const [renaming, setRenaming] = useState(false);
  const [deleting, setDeleting] = useState(false);

  if (role.isPending) {
    return <Loading />;
  }
  if (role.error instanceof ApiError && role.error.status === 404) {
    return <Missing />;
  }
  if (!role.data) {
    return <Failed onRetry={() => void role.refetch()} />;
  }

  const current = role.data;
  const editable = can.has(ROLES_MANAGE);
  const start = new Set((base ?? current).permissions);
  const shown = draft ?? new Set(current.permissions);
  const mine = difference(start, shown);
  const changes = mine.on.length + mine.off.length;
  const allKeys =
    catalog.data?.permissions.map((permission) => permission.key) ?? KNOWN_PERMISSIONS;
  const describedBy = new Map(
    catalog.data?.permissions.map((permission) => [permission.key, permission.description]) ?? [],
  );
  const others = allKeys.filter((key) => !KNOWN_PERMISSIONS.includes(key));
  const groups = [
    ...PERMISSION_GROUPS.map((group) => ({
      id: group.id,
      keys: group.keys.filter((key) => allKeys.includes(key)),
    })),
    ...(others.length ? [{ id: "other" as const, keys: others }] : []),
  ];

  function toggle(key: string, on: boolean) {
    const next = new Set(draft ?? current.permissions);
    if (on) {
      next.add(key);
    } else {
      next.delete(key);
    }
    const unchanged = next.size === start.size && [...next].every((item) => start.has(item));
    setBase(unchanged ? null : (base ?? current));
    setDraft(unchanged ? null : next);
  }

  function discard() {
    setBase(null);
    setDraft(null);
    setConflict(null);
    edit.reset();
  }

  function save(revision: number, permissions: Set<string>) {
    edit.mutate(
      { id, revision, permissions: [...permissions].sort() },
      {
        onSuccess: discard,
        onError: (error) => {
          if (error instanceof ApiError && error.kind === "edit-conflict") {
            // Always from the server: the copy cached a moment ago is the one that lost.
            void client
              .fetchQuery({
                queryKey: ["roles", id],
                staleTime: 0,
                queryFn: () =>
                  unwrap(api.GET("/v1/roles/{role_id}", { params: { path: { role_id: id } } })),
              })
              .then((latest) =>
                setConflict({
                  latest,
                  by: error.problem?.updated_by ?? null,
                  at: error.problem?.updated_at ?? latest.updated_at,
                }),
              );
          }
        },
      },
    );
  }

  function keepBoth(latest: Role) {
    const merged = new Set(latest.permissions);
    mine.on.forEach((key) => merged.add(key));
    mine.off.forEach((key) => merged.delete(key));
    setConflict(null);
    save(latest.revision, merged);
  }

  const label = (key: string) => wordsFor(t, key, describedBy.get(key)).label;
  const summary = [
    ...mine.on.map((key) => t("role.turnedOn", { label: label(key) })),
    ...mine.off.map((key) => t("role.turnedOff", { label: label(key) })),
  ].join(" ");
  const lockedOut = edit.error instanceof ApiError && edit.error.kind === "lockout-refused";
  const holders = current.holders;

  return (
    <Panel>
      <nav
        aria-label={t("role.crumbs")}
        className="flex flex-wrap items-center gap-1.5 text-sm text-muted"
      >
        <Link to={can.has(USERS_MANAGE) ? "/users" : "/users/roles"} className="hover:text-ink">
          {t("users.title")}
        </Link>
        <ChevronRight aria-hidden className="size-3.5 rtl:rotate-180" />
        <Link to="/users/roles" className="hover:text-ink">
          {t("role.rolesCrumb")}
        </Link>
        <ChevronRight aria-hidden className="size-3.5 rtl:rotate-180" />
        <span aria-current="page" className="text-ink">
          {current.name}
        </span>
      </nav>
      <PageHeading
        title={current.name}
        subtitle={current.description}
        action={
          editable ? (
            <Button variant="quiet" size="sm" onClick={() => setRenaming(true)}>
              <Pencil aria-hidden className="size-4" />
              {t("role.rename")}
            </Button>
          ) : null
        }
      />
      <div className="flex flex-wrap gap-2">
        <Chip tone="quiet">
          {current.is_seeded
            ? t("roles.seeded")
            : t("roles.createdOn", { date: formatMoment(current.created_at) })}
        </Chip>
        <Chip tone="quiet">{holdersSummary(t, current)}</Chip>
        <Chip tone="quiet">
          {current.updated_by
            ? t("roles.changedBy", {
                when: formatWhen(current.updated_at),
                name: current.updated_by,
              })
            : t("roles.changed", { when: formatWhen(current.updated_at) })}
        </Chip>
      </div>
      {editable ? null : <Notice tone="quiet">{t("role.readOnly")}</Notice>}

      <div className="flex flex-col gap-4 xl:flex-row xl:items-start">
        <section className="min-w-0 flex-[2] rounded-[20px] bg-white p-5 sm:p-6">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="text-xl font-semibold">{t("role.allows")}</h2>
            <span className="text-sm text-muted">
              {t("role.count", { count: shown.size, total: allKeys.length })}
            </span>
          </div>
          <div className="mt-3.5 flex flex-col gap-5">
            {groups.map((group) =>
              group.keys.length ? (
                <div key={group.id}>
                  <h3 className="text-xs font-semibold tracking-[0.1em] text-muted uppercase">
                    {t(`role.groups.${group.id}`)}
                  </h3>
                  {group.keys.map((key, index) => {
                    const words = wordsFor(t, key, describedBy.get(key));
                    const changed = start.has(key) !== shown.has(key);
                    return (
                      <div
                        key={key}
                        className={cn(
                          "flex items-start gap-4 py-3.5",
                          index < group.keys.length - 1 && !changed && "border-b border-line",
                          changed && "-mx-3 my-1 rounded-[14px] bg-brand-soft px-3",
                        )}
                      >
                        <Switch
                          size="lg"
                          checked={shown.has(key)}
                          disabled={!editable || edit.isPending}
                          onCheckedChange={(on) => toggle(key, on)}
                          aria-label={words.label}
                        />
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="text-[15px] font-semibold">{words.label}</span>
                            <code className="font-mono text-xs text-muted">{key}</code>
                            {changed ? <Chip tone="warn">{t("role.changed")}</Chip> : null}
                          </div>
                          <p className="mt-0.5 text-sm leading-relaxed text-muted">
                            {words.description}
                          </p>
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : null,
            )}
          </div>
        </section>

        <div className="flex min-w-0 flex-1 flex-col gap-4 xl:max-w-[400px]">
          <section className="rounded-[20px] bg-white p-5 sm:p-6">
            <h2 className="text-lg font-semibold">{t("role.holders")}</h2>
            {holders.length ? (
              <ul className="mt-3.5 flex flex-col gap-3">
                {holders.map((holder) => (
                  <li key={holder.id} className="flex items-center gap-3">
                    <Avatar
                      name={holder.display_name}
                      service={holder.kind === "service_account"}
                      size={36}
                    />
                    <span className="text-[15px] font-semibold">{holder.display_name}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-2 text-sm text-muted">{t("role.nobodyHolds")}</p>
            )}
            {can.has(USERS_MANAGE) ? (
              <p className="mt-3.5 text-sm text-muted">
                <Link to="/users" className="text-brand-dark underline underline-offset-2">
                  {t("role.givenOnPeople")}
                </Link>
              </p>
            ) : null}
          </section>
          {editable ? (
            <section className="rounded-[20px] bg-white p-5 sm:p-6">
              <h2 className="text-lg font-semibold">{t("role.deleteTitle")}</h2>
              <p className="mt-2 mb-3.5 text-sm leading-relaxed text-muted">
                {holders.length
                  ? t("role.heldNote", {
                      count: holders.length,
                      names: holders.map((holder) => holder.display_name).join(", "),
                    })
                  : t("role.freeNote")}
              </p>
              <Button
                variant="danger-outline"
                size="sm"
                disabled={holders.length > 0}
                onClick={() => setDeleting(true)}
              >
                <Trash2 aria-hidden className="size-4" />
                {t("role.deleteNamed", { name: current.name })}
              </Button>
            </section>
          ) : null}
        </div>
      </div>

      {changes > 0 ? (
        <div className="sticky bottom-4 flex flex-col gap-3 rounded-[20px] bg-ink p-4 text-white shadow-[0_18px_40px_rgba(17,22,19,0.25)] sm:px-6">
          <div className="flex flex-wrap items-center gap-3.5">
            <div className="min-w-0 flex-[1_1_280px]">
              <div className="font-semibold">{t("role.unsaved", { count: changes })}</div>
              <div className="text-sm text-[#c2c9c4]">
                {summary} {t("role.appliesNow")}
              </div>
            </div>
            <Button
              variant="ghost"
              size="sm"
              className="text-white hover:bg-white/10"
              onClick={discard}
            >
              {t("role.discard")}
            </Button>
            <Button
              size="sm"
              disabled={edit.isPending}
              onClick={() => save((base ?? current).revision, shown)}
            >
              {t("role.save")}
            </Button>
          </div>
          {lockedOut ? <Notice tone="danger">{t("people.lockout")}</Notice> : null}
        </div>
      ) : null}

      <ConflictDialog
        conflict={conflict}
        role={current.name}
        theirs={conflict ? difference(start, new Set(conflict.latest.permissions)) : null}
        mine={mine}
        label={label}
        onKeepBoth={() => conflict && keepBoth(conflict.latest)}
        onSaveMine={() => {
          if (conflict) {
            setConflict(null);
            save(conflict.latest.revision, shown);
          }
        }}
        onClose={() => setConflict(null)}
      />
      <RenameDialog role={renaming ? current : null} onClose={() => setRenaming(false)} />
      <Dialog open={deleting} onOpenChange={(open) => !open && setDeleting(false)}>
        <DialogContent
          title={t("role.deleteConfirm", { name: current.name })}
          description={t("role.deleteBody")}
        >
          {remove.error ? (
            <Notice tone="danger">
              {remove.error instanceof ApiError && remove.error.kind === "role-in-use"
                ? t("role.inUse", { name: current.name })
                : t("common.failed")}
            </Notice>
          ) : null}
          <DialogActions>
            <Button
              variant="danger"
              size="sm"
              disabled={remove.isPending}
              onClick={() =>
                remove.mutate(id, {
                  onSuccess: () => void navigate("/users/roles", { replace: true }),
                })
              }
            >
              {t("role.deleteNamed", { name: current.name })}
            </Button>
            <DialogClose asChild>
              <Button variant="ghost" size="sm">
                {t("common.cancel")}
              </Button>
            </DialogClose>
          </DialogActions>
        </DialogContent>
      </Dialog>
    </Panel>
  );
}

function ConflictDialog({
  conflict,
  role,
  theirs,
  mine,
  label,
  onKeepBoth,
  onSaveMine,
  onClose,
}: {
  conflict: Conflict | null;
  role: string;
  theirs: { on: string[]; off: string[] } | null;
  mine: { on: string[]; off: string[] };
  label: (key: string) => string;
  onKeepBoth: () => void;
  onSaveMine: () => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  if (!conflict || !theirs) {
    return null;
  }
  const describe = (change: { on: string[]; off: string[] }) =>
    [
      ...change.on.map((key) => t("role.turnedOn", { label: label(key) })),
      ...change.off.map((key) => t("role.turnedOff", { label: label(key) })),
    ].join(" ");
  const when = formatWhen(conflict.at);
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        title={t("role.conflictTitle")}
        description={
          conflict.by
            ? t("role.conflictBy", { name: conflict.by, role, when })
            : t("role.conflictAnon", { role, when })
        }
      >
        <Notice tone="warn">
          {theirs.on.length + theirs.off.length ? (
            <p>{t("role.theirChange", { changes: describe(theirs) })}</p>
          ) : null}
          <p>{t("role.yourChange", { changes: describe(mine) })}</p>
        </Notice>
        <DialogActions>
          <Button size="sm" onClick={onKeepBoth}>
            {t("role.keepBoth")}
          </Button>
          <Button variant="ghost" size="sm" onClick={onSaveMine}>
            {t("role.saveMine")}
          </Button>
        </DialogActions>
      </DialogContent>
    </Dialog>
  );
}
