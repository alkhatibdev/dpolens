import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import type { Person, Role } from "@/api/client";
import { useAddPerson, useMakeLink } from "@/api/people";
import { Notice } from "@/components/Notice";
import { Button } from "@/components/ui/button";
import { Dialog, DialogActions, DialogClose, DialogContent } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import { refusalOf } from "./errors";
import type { MadeLink } from "./LinkDialog";
import { RoleChoices } from "./RoleChoices";

/** Name, address and roles; then the link that lets the person choose a password. */
export function AddPersonDialog({
  open,
  roles,
  onClose,
  onAdded,
}: {
  open: boolean;
  roles: readonly Role[];
  onClose: () => void;
  onAdded: (link: MadeLink) => void;
}) {
  const { t } = useTranslation();
  const add = useAddPerson();
  const link = useMakeLink();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [chosen, setChosen] = useState<Set<string>>(new Set());

  function reset() {
    setName("");
    setEmail("");
    setChosen(new Set());
    add.reset();
    link.reset();
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    let person: Person;
    try {
      person = await add.mutateAsync({
        email: email.trim(),
        display_name: name.trim(),
        roles: [...chosen],
      });
    } catch {
      return;
    }
    try {
      const made = await link.mutateAsync(person.id);
      onAdded({ person, secret: made.secret, expiresAt: made.expires_at, fresh: true });
      reset();
    } catch {
      // The person exists; a link can be made from their row.
    }
  }

  const refusal = refusalOf(t, add.error) ?? refusalOf(t, link.error);
  const busy = add.isPending || link.isPending;
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
      <DialogContent title={t("people.addTitle")}>
        <form onSubmit={(event) => void submit(event)} className="flex flex-col gap-5">
          <div className="flex flex-col gap-2">
            <Label htmlFor="person-name">{t("people.name")}</Label>
            <Input
              id="person-name"
              required
              maxLength={200}
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="person-email">{t("people.email")}</Label>
            <Input
              id="person-email"
              type="email"
              required
              maxLength={320}
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </div>
          <RoleChoices roles={roles} chosen={chosen} onChange={setChosen} idPrefix="add-role" />
          <p className="text-sm leading-relaxed text-muted">{t("people.passwordNote")}</p>
          {refusal ? <Notice tone="danger">{refusal}</Notice> : null}
          <DialogActions>
            <Button type="submit" disabled={busy}>
              {name.trim() ? t("people.addNamed", { name: name.trim() }) : t("people.addPlain")}
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
