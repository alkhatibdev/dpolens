import type { TFunction } from "i18next";

import type { Entry } from "@/api/client";
import { formatDate } from "@/lib/format";
import { wordsFor } from "@/lib/permissionWords";

type Details = Record<string, unknown>;

function list(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map(String);
  }
  return typeof value === "string" && value ? [value] : [];
}

function text(value: unknown): string {
  return typeof value === "string"
    ? value
    : value === null || value === undefined
      ? ""
      : String(value);
}

/** A policy by its title, or by its slug where an entry has no title. */
function policy(details: Details): string {
  return text(details.title) || text(details.document);
}

/** One plain sentence for an entry, in the reader's words. The raw action shows when it is new to this build. */
export function describeEntry(t: TFunction, entry: Entry): string {
  const details = entry.details as Details;
  const target = entry.target_user?.display_name ?? t("entries.someone");
  const role = entry.target_id;
  switch (entry.action) {
    case "session.started":
      return t("entries.session_started");
    case "session.ended":
      return t("entries.session_ended");
    case "session.refused":
      return t("entries.session_refused", { target });
    case "user.created": {
      const roles = list(details.roles);
      return roles.length
        ? t("entries.user_created_with", { target, roles: roles.join(", ") })
        : t("entries.user_created", { target });
    }
    case "user.role_granted":
      return t("entries.user_role_granted", { target, role: text(details.role) });
    case "user.role_revoked":
      return t("entries.user_role_revoked", { target, role: text(details.role) });
    case "user.deactivated":
      return t("entries.user_deactivated", { target });
    case "user.activated":
      return t("entries.user_activated", { target });
    case "user.password_set":
      if (details.method === "sign_in_link") {
        return t("entries.user_password_from_link");
      }
      if (details.method === "current_password") {
        return t("entries.user_password_changed");
      }
      return t("entries.user_password_set", { target });
    case "user.sign_in_link_created":
      return t("entries.user_sign_in_link_created", { target });
    case "role.created":
      return t("entries.role_created", { role, count: list(details.permissions).length });
    case "role.seeded":
      return t("entries.role_seeded", { role });
    case "role.deleted":
      return t("entries.role_deleted", { role });
    case "role.permissions_changed": {
      const [granted, ...moreGranted] = list(details.granted);
      const [revoked, ...moreRevoked] = list(details.revoked);
      if (granted && !moreGranted.length && !revoked) {
        return t("entries.role_granted", { role, permission: wordsFor(t, granted).verb });
      }
      if (revoked && !moreRevoked.length && !granted) {
        return t("entries.role_revoked", { role, permission: wordsFor(t, revoked).verb });
      }
      return t("entries.role_changed", { role });
    }
    case "role.renamed": {
      const before = (details.before ?? {}) as Details;
      const after = (details.after ?? {}) as Details;
      return t("entries.role_renamed", { before: text(before.name), after: text(after.name) });
    }
    case "role.described":
      return t("entries.role_described", { role });
    case "pat.created":
      return t("entries.pat_created", { name: text(details.name) });
    case "pat.revoked":
      return t("entries.pat_revoked", { name: text(details.name) });
    case "pat.rejected": {
      const reason = text(details.reason);
      const known = ["revoked", "expired", "owner_inactive"].includes(reason)
        ? t(`entries.pat_reasons.${reason as "revoked" | "expired" | "owner_inactive"}`)
        : reason;
      return t("entries.pat_rejected", {
        owner: entry.target_token?.owner ?? t("entries.someone"),
        name: entry.target_token?.name ?? text(details.prefix),
        reason: known,
      });
    }
    case "laws.selected":
      return t("entries.laws_selected", {
        laws: list(details.after)
          .map((slug) => slug.toUpperCase().replace(/-/g, " "))
          .join(", "),
      });
    case "laws.selection_cleared":
      return t("entries.laws_selection_cleared");
    case "document.drafted":
      return t("entries.document_drafted", { file: text(details.file), policy: policy(details) });
    case "document.flag_accepted":
      return t("entries.document_flag_accepted", {
        count: Array.isArray(details.flags) ? details.flags.length : 0,
        policy: policy(details),
      });
    case "document.draft_edited":
      return t("entries.document_draft_edited", { policy: policy(details) });
    case "document.match_rejected": {
      const own = (key: unknown) => text(key).replace(`${text(details.document)}:`, "");
      return t("entries.document_match_rejected", {
        key: own(details.key),
        policy: policy(details),
        previous: text(details.previous),
        earlier: own(details.earlier),
      });
    }
    case "document.published": {
      const date = text(details.effective_date);
      return t(details.restored ? "entries.document_restored" : "entries.document_published", {
        version: text(details.version),
        policy: policy(details),
        date: date ? formatDate(date) : "",
      });
    }
    case "document.draft_discarded":
      return details.reason === "replaced by a new upload"
        ? t("entries.document_draft_replaced", { policy: policy(details) })
        : details.reason === "the policy was archived"
          ? t("entries.document_draft_archived", { policy: policy(details) })
          : t("entries.document_draft_discarded", { policy: policy(details) });
    case "document.archived":
      return t("entries.document_archived", { policy: policy(details) });
    case "governance_log.exported":
      return t("entries.governance_log_exported", {
        from: text(details.from_seq),
        to: text(details.to_seq),
      });
    case "query_log.retention_purged":
      return t("entries.query_log_retention_purged", { count: Number(details.deleted ?? 0) });
    case "query_log.identities_viewed":
      return details.exported
        ? t("entries.query_log_identities_exported", { count: Number(details.count ?? 0) })
        : t("entries.query_log_identities_viewed", { count: Number(details.count ?? 0) });
    default:
      return entry.action;
  }
}
