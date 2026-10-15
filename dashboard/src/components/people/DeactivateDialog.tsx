import { useTranslation } from "react-i18next";

import type { Person } from "@/api/client";
import { useChangeStatus } from "@/api/people";
import { Notice } from "@/components/Notice";
import { Button } from "@/components/ui/button";
import { Dialog, DialogActions, DialogClose, DialogContent } from "@/components/ui/dialog";

import { refusalOf } from "./errors";

export function DeactivateDialog({
  person,
  onClose,
}: {
  person: Person | null;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const change = useChangeStatus();
  if (!person) {
    return null;
  }
  const refusal = refusalOf(t, change.error, person.display_name);
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) {
          change.reset();
          onClose();
        }
      }}
    >
      <DialogContent
        title={t("people.deactivateTitle", { name: person.display_name })}
        description={t("people.deactivateBody")}
      >
        {refusal ? <Notice tone="danger">{refusal}</Notice> : null}
        <DialogActions>
          <Button
            variant="danger"
            size="sm"
            disabled={change.isPending || refusal !== null}
            onClick={() =>
              change.mutate(
                { id: person.id, status: "deactivated" },
                {
                  onSuccess: () => {
                    change.reset();
                    onClose();
                  },
                },
              )
            }
          >
            {t("people.deactivate")}
          </Button>
          <DialogClose asChild>
            <Button variant="ghost" size="sm">
              {t("common.cancel")}
            </Button>
          </DialogClose>
        </DialogActions>
      </DialogContent>
    </Dialog>
  );
}
