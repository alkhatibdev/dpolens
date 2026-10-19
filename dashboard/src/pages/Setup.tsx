import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, useLocation, useNavigate } from "react-router";

import { neverChosen, useChooseLaws, useLaws } from "@/api/laws";
import { LawChoice } from "@/components/LawChoice";
import { Notice } from "@/components/Notice";
import { Failed, Loading } from "@/components/States";
import { Logo } from "@/components/Logo";
import { Button } from "@/components/ui/button";
import { AccountMenu } from "@/layout/Shell";
import { SETTINGS_MANAGE } from "@/lib/permissions";
import { usePermitted } from "@/session";

/**
 * The one question a new instance asks, of whoever may answer it, as they sign in:
 * which laws apply. Nothing is searched until somebody answers, so there is no
 * deciding later.
 */
export function SetupPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const can = usePermitted();
  const permitted = can.has(SETTINGS_MANAGE);
  const laws = useLaws(permitted);
  const choose = useChooseLaws();
  const [ticked, setTicked] = useState<ReadonlySet<string>>(new Set());
  const then = (location.state as { then?: string } | null)?.then ?? "/";

  if (!permitted || (laws.data && !neverChosen(laws.data))) {
    return <Navigate to={then} replace />;
  }

  function goOn() {
    void navigate(then, { replace: true });
  }

  function toggle(slug: string, on: boolean) {
    const next = new Set(ticked);
    if (on) {
      next.add(slug);
    } else {
      next.delete(slug);
    }
    setTicked(next);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    const order = laws.data?.laws.map((law) => law.slug) ?? [];
    choose.mutate(
      order.filter((slug) => ticked.has(slug)),
      { onSuccess: goOn },
    );
  }

  return (
    <div className="flex min-h-dvh flex-col gap-2 p-2 sm:gap-4 sm:p-4">
      <header className="flex items-center justify-between gap-3 rounded-[20px] bg-white p-2 ps-5 sm:rounded-[24px] sm:p-3.5 sm:ps-6">
        <Logo />
        <AccountMenu />
      </header>
      <main className="flex flex-1 justify-center rounded-[20px] bg-panel px-4 py-8 sm:rounded-[24px] sm:px-7 sm:py-12">
        <div className="w-full max-w-[900px]">
          {laws.isPending ? <Loading /> : null}
          {laws.error ? <Failed onRetry={() => void laws.refetch()} /> : null}
          {laws.data ? (
            <form onSubmit={submit} className="flex flex-col gap-6">
              <div>
                <p className="text-sm font-semibold text-brand-dark">{t("setup.eyebrow")}</p>
                <h1 className="mt-2 text-[30px] leading-[1.12] font-semibold tracking-[-0.025em] sm:text-[40px]">
                  {t("setup.title")}
                </h1>
                <p className="mt-2.5 max-w-[62ch] text-base leading-relaxed text-muted">
                  {t("setup.body")}
                </p>
              </div>
              <fieldset className="min-w-0">
                <legend className="sr-only">{t("laws.loaded")}</legend>
                <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,340px),1fr))] gap-4">
                  {laws.data.laws.map((law) => (
                    <LawChoice
                      key={law.slug}
                      law={law}
                      compact
                      checked={ticked.has(law.slug)}
                      disabled={choose.isPending}
                      onChange={(on) => toggle(law.slug, on)}
                    />
                  ))}
                </div>
              </fieldset>
              {choose.error ? <Notice tone="danger">{t("common.failed")}</Notice> : null}
              <div className="flex flex-wrap items-center gap-3">
                <Button type="submit" disabled={choose.isPending || ticked.size === 0}>
                  {t("setup.save")}
                </Button>
                <span className="text-sm text-muted">{t("setup.note")}</span>
              </div>
            </form>
          ) : null}
        </div>
      </main>
    </div>
  );
}
