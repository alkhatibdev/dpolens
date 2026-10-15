/**
 * How the dashboard groups and names the permission catalog. The keys are the
 * API's; the words are the translation file's. A key the API adds that is not
 * listed here still shows, under "Other", with the API's own description.
 */
export const PERMISSION_GROUPS = [
  { id: "library", keys: ["documents.read", "documents.upload", "documents.publish"] },
  { id: "questions", keys: ["queries.read_own", "queries.read_all", "queries.read_identities"] },
  { id: "governance", keys: ["governance.read"] },
  { id: "administration", keys: ["roles.manage", "users.manage", "settings.manage"] },
  { id: "tokens", keys: ["tokens.create"] },
] as const;

export const KNOWN_PERMISSIONS: readonly string[] = PERMISSION_GROUPS.flatMap(
  (group) => group.keys,
);

export const ROLES_MANAGE = "roles.manage";
export const USERS_MANAGE = "users.manage";
export const TOKENS_CREATE = "tokens.create";
export const DOCUMENTS_READ = "documents.read";
export const QUERIES_READ_ALL = "queries.read_all";
export const QUERIES_READ_OWN = "queries.read_own";
export const QUERIES_READ_IDENTITIES = "queries.read_identities";
export const GOVERNANCE_READ = "governance.read";

/** The translation key for a permission's words, which has no dots of its own. */
export function permissionKey(key: string): string {
  return key.replace(".", "_");
}
