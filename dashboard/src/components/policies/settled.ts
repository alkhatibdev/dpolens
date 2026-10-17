import { useTranslation } from "react-i18next";

import type { DraftFlag } from "@/api/policies";
import { formatTime, formatWhen } from "@/lib/format";
import { FIX_WORDS, isolate, shortKey } from "@/lib/policies";

/** Who settled a flag, how, and when: "Fixed: moved under 3 by Mariam Al Amiri, 09:52". */
export function useSettledLine(slug: string) {
  const { t } = useTranslation();
  return (flag: DraftFlag): string | null => {
    const when = (iso: string) =>
      new Date(iso).toDateString() === new Date().toDateString()
        ? formatTime(iso)
        : formatWhen(iso);
    if (flag.accepted_at) {
      return flag.accepted_by && flag.accepted_by !== "the command line"
        ? t("review.acceptedBy", { name: flag.accepted_by, when: when(flag.accepted_at) })
        : t("review.acceptedAnon", { when: when(flag.accepted_at) });
    }
    if (!flag.resolved_at) {
      return null;
    }
    const by =
      flag.resolved_by && flag.resolved_by !== "the command line" ? flag.resolved_by : null;
    const at = when(flag.resolved_at);
    if (flag.resolution === "match-made") {
      const key = isolate(shortKey(flag.resolution_key ?? "", slug));
      return by
        ? t("review.sameBy", { key, name: by, when: at })
        : t("review.sameAnon", { key, when: at });
    }
    if (flag.resolution && flag.resolution !== "match-rejected") {
      const fix = FIX_WORDS[flag.resolution];
      const key = isolate(shortKey(flag.resolution_key ?? "", slug));
      return by
        ? t(`review.fixedBy.${fix}`, { key, name: by, when: at })
        : t(`review.fixedAnon.${fix}`, { key, when: at });
    }
    return by
      ? t("review.differentBy", { name: by, when: at })
      : t("review.differentAnon", { when: at });
  };
}
