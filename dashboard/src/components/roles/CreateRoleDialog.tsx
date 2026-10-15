import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";

import { ApiError, type Role } from "@/api/client";
import { useCreateRole } from "@/api/roles";
import { FilterButton } from "@/components/Filters";
import { Notice } from "@/components/Notice";
import { Button } from "@/components/ui/button";
import { Dialog, DialogActions, DialogClose, DialogContent } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

/** A name, what it is for, and a role to copy permissions from; the rest on the role's page. */
export function CreateRoleDialog({
  open,
  roles,
  onClose,
}: {
  open: boolean;
  roles: readonly Role[];
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const create = useCreateRole();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [from, setFrom] = useState<Role | null>(null);

  function close() {
    setName("");
    setDescription("");
    setFrom(null);
    create.reset();
    onClose();
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    create.mutate(
      {
        name: name.trim(),
        description: description.trim(),
        permissions: from?.permissions ?? [],
      },
      {
        onSuccess: (role) => {
          close();
          void navigate(`/users/roles/${role.id}`);
        },
      },
    );
  }

  const refusal = create.error
    ? create.error instanceof ApiError && create.error.kind === "already-exists"
      ? t("roles.taken")
      : t("common.failed")
    : null;
  return (
    <Dialog open={open} onOpenChange={(next) => !next && close()}>
      <DialogContent title={t("roles.createTitle")}>
        <form onSubmit={submit} className="flex flex-col gap-5">
          <div className="flex flex-col gap-2">
            <Label htmlFor="role-name">{t("roles.name")}</Label>
            <Input
              id="role-name"
              required
              maxLength={100}
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="role-description">{t("roles.description")}</Label>
            <Input
              id="role-description"
              maxLength={500}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </div>
          <fieldset className="flex flex-col gap-2.5">
            <legend className="mb-2.5 text-sm font-semibold">{t("roles.startFrom")}</legend>
            <div className="flex flex-wrap gap-2">
              <FilterButton pressed={from === null} onClick={() => setFrom(null)}>
                {t("roles.nothing")}
              </FilterButton>
              {roles.map((role) => (
                <FilterButton
                  key={role.id}
                  pressed={from?.id === role.id}
                  onClick={() => setFrom(role)}
                >
                  {role.name}
                </FilterButton>
              ))}
            </div>
            <span className="text-[13px] text-muted">
              {from
                ? t("roles.startsWith", { role: from.name, count: from.permissions.length })
                : t("roles.startsEmpty")}
            </span>
          </fieldset>
          {refusal ? <Notice tone="danger">{refusal}</Notice> : null}
          <DialogActions>
            <Button type="submit" disabled={create.isPending}>
              {t("roles.createSubmit")}
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
