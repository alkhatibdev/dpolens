import { useTranslation } from "react-i18next";

import type { Token } from "@/api/client";
import { useRevokeToken } from "@/api/tokens";
import { Notice } from "@/components/Notice";
import { Button } from "@/components/ui/button";
import { Dialog, DialogActions, DialogClose, DialogContent } from "@/components/ui/dialog";

/** Asked first, because a revoked token cannot be brought back. */
export function RevokeDialog({
  token,
  yours,
  onClose,
}: {
  token: Token | null;
  yours: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const revoke = useRevokeToken();
  if (!token) {
    return null;
  }
  const prefix = `${token.prefix}…`;
  const surface = token.trusted_surface;
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) {
          revoke.reset();
          onClose();
        }
      }}
    >
      <DialogContent
        title={surface ? t("tokens.surfaceTitle") : t("tokens.revokeTitle", { name: token.name })}
        description={
          surface
            ? t("tokens.surfaceBody")
            : yours
              ? t("tokens.revokeYours", { prefix })
              : t("tokens.revokeBody", { owner: token.owner.display_name, prefix })
        }
      >
        {revoke.error ? <Notice tone="danger">{t("common.failed")}</Notice> : null}
        <DialogActions>
          <Button
            variant="danger"
            size="sm"
            disabled={revoke.isPending}
            onClick={() =>
              revoke.mutate(token.id, {
                onSuccess: () => {
                  revoke.reset();
                  onClose();
                },
              })
            }
          >
            {surface ? t("tokens.surfaceSubmit") : t("tokens.revoke")}
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
