import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import type { Person, Role } from "@/api/client";
import { useSetRoles } from "@/api/people";
import { Notice } from "@/components/Notice";
import { Button } from "@/components/ui/button";
import { Dialog, DialogActions, DialogClose, DialogContent } from "@/components/ui/dialog";

import { refusalOf } from "./errors";
import { RoleChoices } from "./RoleChoices";

export function ChangeRolesDialog({
  person,
  roles,
  onClose,
}: {
  person: Person | null;
  roles: readonly Role[];
  onClose: () => void;
}) {
  if (!person) {
    return null;
  }
  return <Form key={person.id} person={person} roles={roles} onClose={onClose} />;
}

function Form({
  person,
  roles,
  onClose,
}: {
  person: Person;
  roles: readonly Role[];
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const save = useSetRoles();
  const [chosen, setChosen] = useState<Set<string>>(new Set(person.roles));

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate({ id: person.id, roles: [...chosen] }, { onSuccess: onClose });
  }

  const refusal = refusalOf(t, save.error, person.display_name);
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent title={t("people.rolesTitle", { name: person.display_name })}>
        <form onSubmit={submit} className="flex flex-col gap-5">
          <RoleChoices roles={roles} chosen={chosen} onChange={setChosen} idPrefix="change-role" />
          <p className="text-sm leading-relaxed text-muted">{t("people.rolesNote")}</p>
          {refusal ? <Notice tone="danger">{refusal}</Notice> : null}
          <DialogActions>
            <Button type="submit" disabled={save.isPending}>
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
