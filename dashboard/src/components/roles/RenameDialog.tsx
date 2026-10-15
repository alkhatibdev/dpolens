import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError, type Role } from "@/api/client";
import { useEditRole } from "@/api/roles";
import { Notice } from "@/components/Notice";
import { Button } from "@/components/ui/button";
import { Dialog, DialogActions, DialogClose, DialogContent } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export function RenameDialog({ role, onClose }: { role: Role | null; onClose: () => void }) {
  if (!role) {
    return null;
  }
  return <Form key={role.id} role={role} onClose={onClose} />;
}

function Form({ role, onClose }: { role: Role; onClose: () => void }) {
  const { t } = useTranslation();
  const edit = useEditRole();
  const [name, setName] = useState(role.name);
  const [description, setDescription] = useState(role.description);

  function submit(event: FormEvent) {
    event.preventDefault();
    // Against the revision on screen now: after a conflict the page has the newer one,
    // and saving again is the person's answer to it.
    edit.mutate(
      { id: role.id, revision: role.revision, name: name.trim(), description: description.trim() },
      { onSuccess: onClose },
    );
  }

  let refusal: string | null = null;
  if (edit.error instanceof ApiError && edit.error.kind === "edit-conflict") {
    refusal = t("role.renameConflict");
  } else if (edit.error instanceof ApiError && edit.error.kind === "already-exists") {
    refusal = t("roles.taken");
  } else if (edit.error) {
    refusal = t("common.failed");
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent title={t("role.renameTitle", { name: role.name })}>
        <form onSubmit={submit} className="flex flex-col gap-5">
          <div className="flex flex-col gap-2">
            <Label htmlFor="rename-name">{t("roles.name")}</Label>
            <Input
              id="rename-name"
              required
              maxLength={100}
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="rename-description">{t("roles.description")}</Label>
            <Input
              id="rename-description"
              maxLength={500}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </div>
          <p className="text-sm leading-relaxed text-muted">{t("role.renameNote")}</p>
          {refusal ? <Notice tone="danger">{refusal}</Notice> : null}
          <DialogActions>
            <Button type="submit" disabled={edit.isPending}>
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
