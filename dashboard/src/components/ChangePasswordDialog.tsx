import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/api/client";
import { Notice } from "@/components/Notice";
import { Button } from "@/components/ui/button";
import { Dialog, DialogActions, DialogClose, DialogContent } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useChangePassword } from "@/session";

/** Changing one's own password, given the current one. Everywhere else is signed out. */
export function ChangePasswordDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation();
  const change = useChangePassword();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");

  function close() {
    setCurrent("");
    setNext("");
    change.reset();
    onClose();
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    change.mutate({ current, new: next });
  }

  let message: string | null = null;
  const failure = change.error;
  if (failure instanceof ApiError && failure.kind === "wrong-password") {
    message = t("password.wrong");
  } else if (failure instanceof ApiError && failure.kind === "weak-password") {
    message = t("password.short");
  } else if (failure instanceof ApiError && failure.kind === "too-many-attempts") {
    message = t("password.tooMany", {
      count: Math.max(1, Math.ceil((failure.retryAfter ?? 60) / 60)),
    });
  } else if (failure) {
    message = t("common.failed");
  }

  return (
    <Dialog open={open} onOpenChange={(value) => !value && close()}>
      {change.isSuccess ? (
        <DialogContent title={t("password.doneTitle")} description={t("password.doneBody")}>
          <DialogActions>
            <DialogClose asChild>
              <Button variant="dark">{t("common.done")}</Button>
            </DialogClose>
          </DialogActions>
        </DialogContent>
      ) : (
        <DialogContent title={t("password.title")}>
          <form onSubmit={submit} className="flex flex-col gap-5">
            <div className="flex flex-col gap-2">
              <Label htmlFor="current-password">{t("password.current")}</Label>
              <Input
                id="current-password"
                type="password"
                autoComplete="current-password"
                required
                value={current}
                onChange={(event) => setCurrent(event.target.value)}
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="changed-password">{t("password.new")}</Label>
              <Input
                id="changed-password"
                type="password"
                autoComplete="new-password"
                required
                minLength={12}
                value={next}
                onChange={(event) => setNext(event.target.value)}
                aria-describedby="changed-password-hint"
              />
              <span id="changed-password-hint" className="text-[13px] text-muted">
                {t("password.hint")}
              </span>
            </div>
            <Notice tone="quiet">{t("password.note")}</Notice>
            {message ? <Notice tone="danger">{message}</Notice> : null}
            <DialogActions>
              <Button type="submit" disabled={change.isPending || !current || next.length < 12}>
                {t("password.submit")}
              </Button>
              <DialogClose asChild>
                <Button type="button" variant="ghost">
                  {t("common.cancel")}
                </Button>
              </DialogClose>
            </DialogActions>
          </form>
        </DialogContent>
      )}
    </Dialog>
  );
}
