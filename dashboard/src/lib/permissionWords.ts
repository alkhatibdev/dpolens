import type { TFunction } from "i18next";

import { en } from "@/i18n/en";
import { permissionKey } from "@/lib/permissions";

type Known = keyof typeof en.permissions;

export interface PermissionWords {
  label: string;
  short: string;
  description: string;
}

/** A permission in the interface's words, or the API's own for one this build doesn't name. */
export function wordsFor(t: TFunction, key: string, fallback = ""): PermissionWords {
  const id = permissionKey(key);
  if (id in en.permissions) {
    const known = id as Known;
    return {
      label: t(`permissions.${known}.label`),
      short: t(`permissions.${known}.short`),
      description: t(`permissions.${known}.description`),
    };
  }
  return { label: key, short: key, description: fallback };
}
