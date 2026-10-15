import type { TFunction } from "i18next";

import { ApiError } from "@/api/client";

/** What a refusal from the people routes means, in the page's words. */
export function refusalOf(t: TFunction, error: unknown, name?: string): string | null {
  if (!error) {
    return null;
  }
  if (error instanceof ApiError) {
    switch (error.kind) {
      case "lockout-refused":
        return name ? t("people.lastManager", { name }) : t("people.lockout");
      case "permission-required":
        return t("people.notYours");
      case "already-exists":
        return t("people.taken");
    }
  }
  return t("common.failed");
}
