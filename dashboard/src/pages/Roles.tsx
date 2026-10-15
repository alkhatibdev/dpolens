import { ArrowUpRight, Plus } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import type { Role } from "@/api/client";
import { usePeople } from "@/api/people";
import { usePermissions, useRoles } from "@/api/roles";
import { Avatar } from "@/components/Avatar";
import { PageHeading } from "@/components/Page";
import { UsersTabs } from "@/components/people/UsersTabs";
import { CreateRoleDialog } from "@/components/roles/CreateRoleDialog";
import { holdersSummary } from "@/components/roles/holders";
import { Chip, Failed, Loading, Panel } from "@/components/States";
import { Button } from "@/components/ui/button";
import { formatMoment, formatWhen } from "@/lib/format";
import { ROLES_MANAGE, USERS_MANAGE } from "@/lib/permissions";
import { cn } from "@/lib/utils";
import { usePermitted } from "@/session";

/** Eleven pills, one per permission, filled for each the role allows. */
function Meter({ granted, total }: { granted: number; total: number }) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-2">
      <div
        role="img"
        aria-label={t("roles.permissionsOf", { count: granted, total })}
        className="flex gap-1"
      >
        {Array.from({ length: total }, (_, index) => (
          <span
            key={index}
            className={cn("h-2.5 flex-1 rounded-full", index < granted ? "bg-brand" : "bg-line")}
          />
        ))}
      </div>
      <span aria-hidden className="text-[13px] text-ink-2">
        {t("roles.permissionsOf", { count: granted, total })}
      </span>
    </div>
  );
}

function RoleCard({ role, total }: { role: Role; total: number }) {
  const { t } = useTranslation();
  const changed = formatWhen(role.updated_at);
  return (
    <Link
      to={`/users/roles/${role.id}`}
      className="flex min-w-0 flex-col gap-3.5 rounded-[20px] bg-white p-5 text-ink hover:shadow-[0_8px_24px_rgba(17,22,19,0.07)] sm:p-6"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-[21px] leading-snug font-semibold">{role.name}</h2>
          {role.description ? (
            <p className="mt-1 text-sm leading-relaxed text-muted">{role.description}</p>
          ) : null}
        </div>
        <span className="grid size-10 shrink-0 place-items-center rounded-full border-[1.5px] border-ink">
          <ArrowUpRight aria-hidden className="size-4" />
        </span>
      </div>
      <Meter granted={role.permissions.length} total={total} />
      <div className="flex flex-wrap items-center justify-between gap-2.5 border-t border-line pt-3.5">
        <span className="flex items-center gap-2.5 text-sm text-ink-2">
          <span className="flex">
            {role.holders.slice(0, 4).map((holder, index) => (
              <Avatar
                key={holder.id}
                name={holder.display_name}
                service={holder.kind === "service_account"}
                size={28}
                className={cn("ring-2 ring-white", index > 0 && "-ms-2")}
              />
            ))}
          </span>
          {holdersSummary(t, role)}
        </span>
        <Chip tone="quiet">
          {role.is_seeded
            ? t("roles.seeded")
            : t("roles.createdOn", { date: formatMoment(role.created_at) })}
        </Chip>
      </div>
      <div className="-mt-1.5 text-[13px] text-muted">
        {role.updated_by
          ? t("roles.changedBy", { when: changed, name: role.updated_by })
          : t("roles.changed", { when: changed })}
      </div>
    </Link>
  );
}

export function RolesPage() {
  const { t } = useTranslation();
  const can = usePermitted();
  const roles = useRoles();
  const catalog = usePermissions();
  const people = usePeople(can.has(USERS_MANAGE));
  const [creating, setCreating] = useState(false);
  const all = roles.data?.roles ?? [];
  const total = catalog.data?.permissions.length ?? 11;

  return (
    <Panel>
      <PageHeading
        title={t("users.title")}
        subtitle={t("users.subtitle")}
        action={
          can.has(ROLES_MANAGE) ? (
            <Button onClick={() => setCreating(true)}>
              <Plus aria-hidden className="size-4" />
              {t("roles.create")}
            </Button>
          ) : null
        }
      />
      <UsersTabs people={people.data?.people.length} roles={all.length} />
      {roles.isPending ? <Loading /> : null}
      {roles.error ? <Failed onRetry={() => void roles.refetch()} /> : null}
      {roles.data ? (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(min(100%,420px),1fr))] gap-4">
          {all.map((role) => (
            <RoleCard key={role.id} role={role} total={total} />
          ))}
        </div>
      ) : null}
      <p className="text-sm leading-relaxed text-muted">{t("roles.note")}</p>
      <CreateRoleDialog open={creating} roles={all} onClose={() => setCreating(false)} />
    </Panel>
  );
}
