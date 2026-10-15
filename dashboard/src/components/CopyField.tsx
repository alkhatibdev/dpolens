import { Check, Copy } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { copyText } from "@/lib/copy";
import { cn } from "@/lib/utils";

/** Something to copy, shown in full, with a button that says when it worked. */
export function CopyField({
  value,
  label,
  emphasis = false,
}: {
  value: string;
  label: string;
  emphasis?: boolean;
}) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) {
      return;
    }
    const timer = window.setTimeout(() => setCopied(false), 2000);
    return () => window.clearTimeout(timer);
  }, [copied]);

  return (
    <div className="flex items-center gap-2 rounded-[14px] bg-field py-1.5 ps-4 pe-1.5">
      <code className="min-w-0 flex-1 font-mono text-[13px] leading-relaxed break-all text-ink">
        {value}
      </code>
      <Button
        type="button"
        size="sm"
        variant={emphasis ? "primary" : "quiet"}
        aria-label={label}
        className={cn(!emphasis && "bg-white")}
        onClick={() => void copyText(value).then(() => setCopied(true))}
      >
        {copied ? (
          <Check aria-hidden className="size-4" />
        ) : (
          <Copy aria-hidden className="size-4" />
        )}
        {copied ? t("common.copied") : t("common.copy")}
      </Button>
    </div>
  );
}
