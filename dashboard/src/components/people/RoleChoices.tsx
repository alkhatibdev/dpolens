import { useTranslation } from "react-i18next";

import type { Role } from "@/api/client";
import { ChoiceCard } from "@/components/ChoiceCard";

/** Every role as a card to tick, with what it is for and how many hold it. */
export function RoleChoices({
  roles,
  chosen,
  onChange,
  idPrefix,
}: {
  roles: readonly Role[];
  chosen: ReadonlySet<string>;
  onChange: (next: Set<string>) => void;
  idPrefix: string;
}) {
  const { t } = useTranslation();
  return (
    <fieldset className="flex flex-col gap-2.5">
      <legend className="mb-2.5 text-sm font-semibold">{t("people.roles")}</legend>
      {roles.map((role) => (
        <ChoiceCard
          key={role.id}
          id={`${idPrefix}-${role.id}`}
          checked={chosen.has(role.name)}
          onChange={(checked) => {
            const next = new Set(chosen);
            if (checked) {
              next.add(role.name);
            } else {
              next.delete(role.name);
            }
            onChange(next);
          }}
          title={role.name}
          description={role.description}
          aside={
            role.holders.length
              ? t("people.heldBy", { count: role.holders.length })
              : t("people.nobodyYet")
          }
        />
      ))}
    </fieldset>
  );
}
