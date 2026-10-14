import { Check, Copy } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { Clause } from "@/api/client";
import { Button } from "@/components/ui/button";
import { quotationFor } from "@/lib/citation";
import { copyText } from "@/lib/copy";
import { cn } from "@/lib/utils";

function useCopied(): [boolean, (text: string) => Promise<void>] {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) {
      return;
    }
    const timer = window.setTimeout(() => setCopied(false), 2000);
    return () => window.clearTimeout(timer);
  }, [copied]);
  return [
    copied,
    async (text: string) => {
      await copyText(text);
      setCopied(true);
    },
  ];
}

/** A clause's key, as a button that copies its text and its citation. */
export function KeyButton({
  clause,
  breadcrumb,
  label,
  emphasis = false,
}: {
  clause: Clause;
  breadcrumb: readonly Clause[];
  label: string;
  emphasis?: boolean;
}) {
  const { t } = useTranslation();
  const [copied, copy] = useCopied();
  return (
    <button
      type="button"
      onClick={() => void copy(quotationFor(clause, breadcrumb))}
      aria-label={t("clause.copyKey", { key: clause.key })}
      title={t("clause.copy")}
      className={cn(
        "inline-flex h-7 min-w-11 items-center justify-center gap-1 rounded-full px-2.5 font-mono text-xs font-medium transition-colors",
        emphasis
          ? "bg-brand-soft text-brand-dark hover:bg-brand-mid/50"
          : "bg-field text-ink-2 hover:bg-line",
      )}
    >
      {copied ? <Check aria-hidden className="size-3.5" /> : null}
      <span aria-live="polite">{copied ? t("clause.copied") : label}</span>
    </button>
  );
}

export function CopyCitationButton({
  clause,
  breadcrumb,
  variant = "outline",
  className,
}: {
  clause: Clause;
  breadcrumb: readonly Clause[];
  variant?: "outline" | "primary";
  className?: string;
}) {
  const { t } = useTranslation();
  const [copied, copy] = useCopied();
  return (
    <Button
      variant={variant}
      size="sm"
      className={className}
      onClick={() => void copy(quotationFor(clause, breadcrumb))}
    >
      {copied ? <Check aria-hidden className="size-4" /> : <Copy aria-hidden className="size-4" />}
      <span aria-live="polite">{copied ? t("clause.copied") : t("clause.copy")}</span>
    </Button>
  );
}
