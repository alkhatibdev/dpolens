import { Ellipsis, Link as LinkIcon, UserPlus, Users, UserCheck, UserX } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Navigate } from "react-router";

import type { Person } from "@/api/client";
import { useChangeStatus, useMakeLink, usePeople } from "@/api/people";
import { useRoles } from "@/api/roles";
import { Avatar } from "@/components/Avatar";
import { FilterButton, FindBox } from "@/components/Filters";
import { PageHeading, TableCard, td, th } from "@/components/Page";
import { AddPersonDialog } from "@/components/people/AddPersonDialog";
import { ChangeRolesDialog } from "@/components/people/ChangeRolesDialog";
import { DeactivateDialog } from "@/components/people/DeactivateDialog";
import { LinkDialog, type MadeLink } from "@/components/people/LinkDialog";
import { UsersTabs } from "@/components/people/UsersTabs";
import { Chip, Failed, Loading, Panel } from "@/components/States";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { formatDate, formatWeekday } from "@/lib/format";
import { ROLES_MANAGE, USERS_MANAGE } from "@/lib/permissions";
import { usePermitted, useSession } from "@/session";

type Filter = "everyone" | "active" | "deactivated" | "services";

function matches(person: Person, filter: Filter, query: string): boolean {
  const wanted = query.trim().toLowerCase();
  if (
    wanted &&
    !person.display_name.toLowerCase().includes(wanted) &&
    !person.email.toLowerCase().includes(wanted)
  ) {
    return false;
  }
  switch (filter) {
    case "active":
      return person.status === "active";
    case "deactivated":
      return person.status === "deactivated";
    case "services":
      return person.kind === "service_account";
    default:
      return true;
  }
}

function Status({ person }: { person: Person }) {
  const { t } = useTranslation();
  if (person.status === "deactivated") {
    return (
      <Chip tone="quiet">
        {t("people.deactivatedOn", { date: formatDate(person.deactivated_at ?? "", "short") })}
      </Chip>
    );
  }
  if (person.kind === "service_account") {
    return <Chip tone="quiet">{t("people.serviceAccount")}</Chip>;
  }
  if (!person.has_password) {
    return (
      <div>
        <Chip tone="warn">
          {person.sign_in_link_expires_at ? t("people.noPassword") : t("people.noPasswordYet")}
        </Chip>
        {person.sign_in_link_expires_at ? (
          <div className="mt-1.5 text-xs text-muted">
            {t("people.linkUntil", { date: formatWeekday(person.sign_in_link_expires_at) })}
          </div>
        ) : null}
      </div>
    );
  }
  return <Chip>{t("people.isActive")}</Chip>;
}

function addedOn(iso: string, t: (key: "people.today") => string): string {
  return new Date(iso).toDateString() === new Date().toDateString()
    ? t("people.today")
    : formatDate(iso, "short");
}

export function PeoplePage() {
  const { t } = useTranslation();
  const can = usePermitted();
  const session = useSession();
  const people = usePeople(can.has(USERS_MANAGE));
  const roles = useRoles();
  const reactivate = useChangeStatus();
  const makeLink = useMakeLink();
  const [filter, setFilter] = useState<Filter>("everyone");
  const [query, setQuery] = useState("");
  const [adding, setAdding] = useState(false);
  const [link, setLink] = useState<MadeLink | null>(null);
  const [changing, setChanging] = useState<Person | null>(null);
  const [deactivating, setDeactivating] = useState<Person | null>(null);

  if (!can.has(USERS_MANAGE)) {
    return <Navigate to={can.has(ROLES_MANAGE) ? "/users/roles" : "/library"} replace />;
  }

  const everyone = people.data?.people ?? [];
  const shown = everyone.filter((person) => matches(person, filter, query));
  const myId = session.data?.account.id;
  const allRoles = roles.data?.roles ?? [];

  function newLink(person: Person) {
    makeLink.mutate(person.id, {
      onSuccess: (made) =>
        setLink({ person, secret: made.secret, expiresAt: made.expires_at, fresh: false }),
    });
  }

  return (
    <Panel>
      <PageHeading
        title={t("users.title")}
        subtitle={t("users.subtitle")}
        action={
          <Button onClick={() => setAdding(true)}>
            <UserPlus aria-hidden className="size-4" />
            {t("people.add")}
          </Button>
        }
      />
      <UsersTabs people={everyone.length} roles={allRoles.length} />
      <div className="flex flex-wrap items-center gap-2">
        <FindBox label={t("people.search")} value={query} onChange={setQuery} />
        {(["everyone", "active", "deactivated", "services"] as const).map((value) => (
          <FilterButton key={value} pressed={filter === value} onClick={() => setFilter(value)}>
            {t(`people.${value}`)}
          </FilterButton>
        ))}
      </div>

      {people.isPending ? <Loading /> : null}
      {people.error ? <Failed onRetry={() => void people.refetch()} /> : null}
      {people.data ? (
        <TableCard>
          <table className="w-full min-w-[900px] border-collapse">
            <thead>
              <tr>
                <th scope="col" className={th}>
                  {t("people.person")}
                </th>
                <th scope="col" className={th}>
                  {t("people.roles")}
                </th>
                <th scope="col" className={th}>
                  {t("people.status")}
                </th>
                <th scope="col" className={th}>
                  {t("people.tokens")}
                </th>
                <th scope="col" className={th}>
                  {t("people.added")}
                </th>
                <th scope="col" className={th}>
                  <span className="sr-only">{t("people.actions", { name: "" })}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {shown.map((person) => {
                const you = person.id === myId;
                const service = person.kind === "service_account";
                return (
                  <tr key={person.id}>
                    <td className={td}>
                      <div className="flex min-w-0 items-center gap-3">
                        <Avatar name={person.display_name} service={service} size={36} />
                        <div className="min-w-0">
                          <div className="font-semibold">
                            {person.display_name}{" "}
                            {you ? (
                              <span className="text-[13px] font-normal text-muted">
                                {t("people.you")}
                              </span>
                            ) : null}
                          </div>
                          <div className="text-[13px] break-all text-muted">
                            {person.acts_for_others ? t("people.runsWithInstance") : person.email}
                          </div>
                        </div>
                      </div>
                    </td>
                    <td className={td}>
                      {person.acts_for_others ? (
                        <span className="text-[13px] text-muted">{t("people.actsForOthers")}</span>
                      ) : person.roles.length ? (
                        <div className="flex flex-wrap gap-1.5">
                          {person.roles.map((role) => (
                            <Chip key={role} tone="quiet">
                              {role}
                            </Chip>
                          ))}
                        </div>
                      ) : (
                        <span className="text-[13px] text-muted">{t("people.noRoles")}</span>
                      )}
                    </td>
                    <td className={td}>
                      <Status person={person} />
                    </td>
                    <td className={`${td} tabular-nums`}>{person.working_tokens}</td>
                    <td className={`${td} text-sm whitespace-nowrap text-ink-2`}>
                      {addedOn(person.created_at, t)}
                    </td>
                    <td className={`${td} py-2.5 text-end`}>
                      {person.acts_for_others ? null : (
                        <DropdownMenu>
                          <DropdownMenuTrigger
                            aria-label={t("people.actions", { name: person.display_name })}
                            className="grid size-10 place-items-center rounded-full text-ink-2 hover:bg-field data-[state=open]:bg-field"
                          >
                            <Ellipsis aria-hidden className="size-5" />
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            {person.status === "active" ? (
                              <>
                                <DropdownMenuItem onSelect={() => setChanging(person)}>
                                  <Users aria-hidden />
                                  {t("people.changeRoles")}
                                </DropdownMenuItem>
                                {service ? null : (
                                  <DropdownMenuItem onSelect={() => newLink(person)}>
                                    <LinkIcon aria-hidden />
                                    {t("people.makeLink")}
                                  </DropdownMenuItem>
                                )}
                                {you ? null : (
                                  <DropdownMenuItem
                                    onSelect={() => setDeactivating(person)}
                                    className="text-danger-ink [&_svg]:text-danger-ink"
                                  >
                                    <UserX aria-hidden />
                                    {t("people.deactivate")}
                                  </DropdownMenuItem>
                                )}
                              </>
                            ) : (
                              <DropdownMenuItem
                                onSelect={() =>
                                  reactivate.mutate({ id: person.id, status: "active" })
                                }
                              >
                                <UserCheck aria-hidden />
                                {t("people.reactivate")}
                              </DropdownMenuItem>
                            )}
                          </DropdownMenuContent>
                        </DropdownMenu>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {shown.length === 0 ? <p className="px-4 py-5 text-muted">{t("people.none")}</p> : null}
        </TableCard>
      ) : null}

      <AddPersonDialog
        open={adding}
        roles={allRoles}
        onClose={() => setAdding(false)}
        onAdded={(made) => {
          setAdding(false);
          setLink(made);
        }}
      />
      <LinkDialog link={link} onClose={() => setLink(null)} />
      <ChangeRolesDialog person={changing} roles={allRoles} onClose={() => setChanging(null)} />
      <DeactivateDialog person={deactivating} onClose={() => setDeactivating(null)} />
    </Panel>
  );
}
