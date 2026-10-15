import { useTranslation } from "react-i18next";

import type { Person } from "@/api/client";
import { linkFor } from "@/api/people";
import { CopyField } from "@/components/CopyField";
import { Notice } from "@/components/Notice";
import { Button } from "@/components/ui/button";
import { Dialog, DialogActions, DialogClose, DialogContent } from "@/components/ui/dialog";
import { formatDeadline } from "@/lib/format";

export interface MadeLink {
  person: Person;
  secret: string;
  expiresAt: string;
  /** For someone just added, rather than a new link for someone already here. */
  fresh: boolean;
}

/** The link, once, with how to hand it over. */
export function LinkDialog({ link, onClose }: { link: MadeLink | null; onClose: () => void }) {
  const { t } = useTranslation();
  if (!link) {
    return null;
  }
  const name = link.person.display_name;
  const date = formatDeadline(link.expiresAt);
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        title={link.fresh ? t("people.linkTitle", { name }) : t("people.newLinkTitle", { name })}
        description={
          link.fresh ? t("people.linkBody", { name, date }) : t("people.newLinkBody", { date })
        }
      >
        <CopyField value={linkFor(link.secret)} label={t("people.copyLink")} emphasis />
        <Notice tone="quiet">{t("people.linkAdvice")}</Notice>
        <DialogActions>
          <DialogClose asChild>
            <Button variant="dark">{t("common.done")}</Button>
          </DialogClose>
        </DialogActions>
      </DialogContent>
    </Dialog>
  );
}
