import { useTranslation } from "react-i18next";

import type { DraftFlag } from "@/api/policies";
import { formatTime, formatWhen } from "@/lib/format";

/** Who settled a flag, how, and when: "Accepted as read by Mariam Al Amiri, 09:53". */
export function useSettledLine() {
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
    if (flag.resolved_at) {
      return flag.resolved_by && flag.resolved_by !== "the command line"
        ? t("review.differentBy", { name: flag.resolved_by, when: when(flag.resolved_at) })
        : t("review.differentAnon", { when: when(flag.resolved_at) });
    }
    return null;
  };
}
