import type { TFunction } from "i18next";

import type { Role } from "@/api/client";

/** "4 people and 1 service account", or "Nobody yet". */
export function holdersSummary(t: TFunction, role: Role): string {
  const people = role.holders.filter((holder) => holder.kind === "person").length;
  const services = role.holders.length - people;
  if (!people && !services) {
    return t("roles.nobody");
  }
  const parts: string[] = [
    ...(people ? [String(t("roles.people", { count: people }))] : []),
    ...(services ? [String(t("roles.services", { count: services }))] : []),
  ];
  const [first = "", second] = parts;
  return second ? t("roles.and", { first, second }) : first;
}
