import { Lock } from "lucide-react";
import { useTranslation } from "react-i18next";

import { en } from "@/i18n/en";

const PLACEHOLDER = /\[redacted:([a-z0-9_]+)\]/g;

type Known = keyof typeof en.logs.removedKinds;

/** A question as it was stored, each placeholder shown as a chip saying what was taken out. */
export function Redacted({ text }: { text: string }) {
  const { t } = useTranslation();
  const parts: React.ReactNode[] = [];
  let last = 0;
  for (const match of text.matchAll(PLACEHOLDER)) {
    const kind = match[1] ?? "";
    parts.push(text.slice(last, match.index));
    const what = kind in en.logs.removedKinds ? t(`logs.removedKinds.${kind as Known}`) : kind;
    parts.push(
      <span
        key={`${match.index}-${kind}`}
        className="mx-0.5 inline-flex items-center gap-1 rounded-full bg-field px-2.5 align-[1px] text-[13px] font-medium whitespace-nowrap text-ink-2"
      >
        <Lock aria-hidden className="size-3" />
        {t("logs.removed", { what })}
      </span>,
    );
    last = (match.index ?? 0) + match[0].length;
  }
  parts.push(text.slice(last));
  return (
    <span dir="auto" className="block">
      {parts}
    </span>
  );
}
