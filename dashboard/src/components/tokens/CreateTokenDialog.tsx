import { CalendarDays } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import type { TokenMade } from "@/api/client";
import { useMakeToken } from "@/api/tokens";
import { ChoiceCard } from "@/components/ChoiceCard";
import { FilterButton } from "@/components/Filters";
import { Notice } from "@/components/Notice";
import { Button } from "@/components/ui/button";
import { Dialog, DialogActions, DialogClose, DialogContent } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { formatDate } from "@/lib/format";
import { wordsFor } from "@/lib/permissionWords";
import { DOCUMENTS_READ, KNOWN_PERMISSIONS, TOKENS_CREATE } from "@/lib/permissions";

type Expiry = "never" | "days30" | "days90" | "year" | "pick";

const DAYS: Record<Exclude<Expiry, "never" | "pick">, number> = {
  days30: 30,
  days90: 90,
  year: 365,
};

const DAY = 24 * 60 * 60 * 1000;

function endOf(expiry: Expiry, picked: string, now: number): Date | null {
  if (expiry === "never") {
    return null;
  }
  if (expiry === "pick") {
    return picked ? new Date(`${picked}T23:59:59`) : null;
  }
  return new Date(now + DAYS[expiry] * DAY);
}

interface Props {
  held: ReadonlySet<string>;
  onClose: () => void;
  onMade: (token: TokenMade) => void;
}

/** A name, what it may do (never more than its maker), and when it stops working. */
export function CreateTokenDialog({ open, ...props }: Props & { open: boolean }) {
  // Mounted afresh each time, so its dates count from when it was opened.
  return open ? <Form {...props} /> : null;
}

function Form({ held, onClose, onMade }: Props) {
  const { t } = useTranslation();
  const make = useMakeToken();
  const [name, setName] = useState("");
  const [chosen, setChosen] = useState<Set<string>>(new Set([DOCUMENTS_READ]));
  const [expiry, setExpiry] = useState<Expiry>("days90");
  const [picked, setPicked] = useState("");
  // Read once, so the dates the dialog shows hold still while it is open.
  const [now] = useState(() => Date.now());

  // Tokens are made in the dashboard only, so the permission to make them is no use to one.
  const offered = KNOWN_PERMISSIONS.filter((key) => held.has(key) && key !== TOKENS_CREATE);
  const end = endOf(expiry, picked, now);

  function close() {
    make.reset();
    onClose();
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    make.mutate(
      {
        name: name.trim(),
        permissions: [...chosen].sort(),
        expires_at: end?.toISOString() ?? null,
      },
      {
        onSuccess: (token) => {
          close();
          onMade(token);
        },
      },
    );
  }

  return (
    <Dialog open onOpenChange={(next) => !next && close()}>
      <DialogContent title={t("tokens.createTitle")}>
        <form onSubmit={submit} className="flex flex-col gap-5">
          <div className="flex flex-col gap-2">
            <Label htmlFor="token-name">{t("tokens.name")}</Label>
            <Input
              id="token-name"
              required
              maxLength={100}
              placeholder={t("tokens.namePlaceholder")}
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
            <span className="text-[13px] text-muted">{t("tokens.nameHint")}</span>
          </div>
          <fieldset className="flex flex-col gap-2.5">
            <legend className="mb-1 text-sm font-semibold">{t("tokens.canLegend")}</legend>
            <span className="mb-1 text-[13px] text-muted">{t("tokens.canHint")}</span>
            {offered.map((key) => {
              const words = wordsFor(t, key);
              const own = key === "queries.read_own";
              return (
                <ChoiceCard
                  key={key}
                  id={`token-${key}`}
                  checked={chosen.has(key)}
                  onChange={(checked) => {
                    const next = new Set(chosen);
                    if (checked) {
                      next.add(key);
                    } else {
                      next.delete(key);
                    }
                    setChosen(next);
                  }}
                  title={
                    <>
                      {own ? t("tokens.ownQuestions") : words.label}{" "}
                      <code className="ms-1 font-mono text-xs font-normal text-muted">{key}</code>
                    </>
                  }
                  description={
                    key === DOCUMENTS_READ
                      ? t("tokens.enough")
                      : own
                        ? t("tokens.ownQuestionsNote")
                        : words.description
                  }
                />
              );
            })}
          </fieldset>
          <fieldset className="flex flex-col gap-2.5">
            <legend className="mb-2.5 text-sm font-semibold">{t("tokens.expiresLegend")}</legend>
            <div className="flex flex-wrap gap-2">
              {(["never", "days30", "days90", "year", "pick"] as const).map((value) => (
                <FilterButton
                  key={value}
                  pressed={expiry === value}
                  onClick={() => setExpiry(value)}
                >
                  {value === "pick" ? (
                    <CalendarDays aria-hidden className="me-1.5 inline size-4" />
                  ) : null}
                  {t(`tokens.${value}`)}
                </FilterButton>
              ))}
            </div>
            {expiry === "pick" ? (
              <Input
                type="date"
                aria-label={t("tokens.pickLabel")}
                min={new Date(now + DAY).toISOString().slice(0, 10)}
                value={picked}
                onChange={(event) => setPicked(event.target.value)}
                className="max-w-[240px]"
              />
            ) : null}
            <span className="text-[13px] text-muted">
              {end
                ? t("tokens.stops", { date: formatDate(end.toISOString()) })
                : expiry === "never"
                  ? t("tokens.forever")
                  : null}
            </span>
          </fieldset>
          {make.error ? <Notice tone="danger">{t("common.failed")}</Notice> : null}
          <DialogActions>
            <Button
              type="submit"
              disabled={make.isPending || chosen.size === 0 || (expiry === "pick" && !picked)}
            >
              {t("tokens.createSubmit")}
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
