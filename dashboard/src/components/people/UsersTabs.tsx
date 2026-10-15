import { useTranslation } from "react-i18next";

import { SectionTabs } from "@/components/Segmented";
import { USERS_MANAGE } from "@/lib/permissions";
import { usePermitted } from "@/session";

/** People and Roles; People only for someone who manages people. */
export function UsersTabs({ people, roles }: { people?: number; roles?: number }) {
  const { t } = useTranslation();
  const can = usePermitted();
  const items = [
    ...(can.has(USERS_MANAGE)
      ? [{ to: "/users", end: true, label: t("users.people", { count: people ?? 0 }) }]
      : []),
    { to: "/users/roles", end: true, label: t("users.roles", { count: roles ?? 0 }) },
  ];
  return <SectionTabs label={t("users.sections")} items={items} />;
}
