import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { Button } from "@/components/ui/button";

export function Loading() {
  const { t } = useTranslation();
  return (
    <div role="status" className="grid gap-3 p-1" aria-label={t("app.loading")}>
      {[0, 1, 2].map((row) => (
        <div key={row} className="h-24 animate-pulse rounded-[20px] bg-white/70" />
      ))}
    </div>
  );
}

export function Failed({ onRetry }: { onRetry?: () => void }) {
  const { t } = useTranslation();
  return (
    <div role="alert" className="rounded-[20px] bg-white p-6">
      <p className="text-base">{t("errors.loadFailed")}</p>
      {onRetry ? (
        <Button variant="dark" size="sm" className="mt-4" onClick={onRetry}>
          {t("errors.retry")}
        </Button>
      ) : null}
    </div>
  );
}

export function Missing() {
  const { t } = useTranslation();
  return (
    <div className="rounded-[20px] bg-white p-6">
      <p className="text-base">{t("errors.notFound")}</p>
      <Button asChild variant="dark" size="sm" className="mt-4">
        <Link to="/library">{t("errors.back")}</Link>
      </Button>
    </div>
  );
}

/** The grey panel a page's content sits in, under the top bar. */
export function Panel({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-col gap-4 rounded-[20px] bg-panel p-3 sm:rounded-[24px] sm:p-7">
      {children}
    </div>
  );
}

export function Chip({
  children,
  tone = "plain",
  lang,
}: {
  children: ReactNode;
  tone?: "plain" | "brand" | "soft" | "quiet" | "warn";
  lang?: string;
}) {
  const tones = {
    plain: "border border-line-strong bg-white",
    brand: "bg-brand font-semibold text-white",
    soft: "bg-brand-soft font-semibold text-brand-dark",
    quiet: "bg-field",
    warn: "bg-warn-soft font-semibold text-warn-ink",
  } as const;
  return (
    <span lang={lang} className={`rounded-full px-3 py-1.5 text-[13px] ${tones[tone]}`}>
      {children}
    </span>
  );
}
