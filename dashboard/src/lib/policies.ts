import { ApiError } from "@/api/client";
import type { DraftClause, DraftFlag, PolicyDraft } from "@/api/policies";

export const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;

/** What the API accepts as a key prefix: lower-case Latin letters, digits and hyphens. */
export const PREFIX = /^[a-z0-9][a-z0-9-]{0,59}$/;

/**
 * A key prefix from a file's name, as the API would make one: "Data Retention
 * (2026).docx" gives "data-retention-2026". A name with no Latin letters gives
 * nothing, and the person types one.
 */
export function prefixFrom(name: string): string {
  const stem = name.replace(/\.[^.]+$/, "");
  return stem
    .normalize("NFKD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60)
    .replace(/-+$/, "");
}

/** Why a file will not be read, before it is sent, or null when it may be. */
export function refusalFor(file: File): "pdf" | "doc" | "format" | "tooLarge" | null {
  const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
  if (!["docx", "md", "markdown"].includes(extension)) {
    return extension === "pdf" ? "pdf" : extension === "doc" ? "doc" : "format";
  }
  return file.size > MAX_UPLOAD_BYTES ? "tooLarge" : null;
}

export function isWord(name: string | null | undefined): boolean {
  return (name ?? "").toLowerCase().endsWith(".docx");
}

/** "48 KB", "1.2 MB": a file's size as people read it. */
export function formatSize(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} bytes`;
  }
  if (bytes < 1024 * 1024) {
    return `${Math.round(bytes / 1024)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** A key without the policy's own prefix, as the review shows it: "4.2" for "retention:4.2". */
export function shortKey(key: string, slug: string): string {
  return key.startsWith(`${slug}:`) ? key.slice(slug.length + 1) : key;
}

/** Every clause, depth first, in the order the file has them. */
export function walk(clauses: readonly DraftClause[]): DraftClause[] {
  return clauses.flatMap((clause) => [clause, ...walk(clause.children)]);
}

export function isSettled(flag: DraftFlag): boolean {
  return flag.accepted_at !== null || flag.resolved_at !== null;
}

/** How many of a draft's flags are still open. */
export function openCount(draft: PolicyDraft): number {
  return draft.flags.filter((flag) => !isSettled(flag)).length;
}

/** Who changed a draft after it was read, and when, as the API's refusal says. */
export interface Conflict {
  by: string | null;
  at: string;
}

export function conflictOf(error: unknown): Conflict | null {
  if (error instanceof ApiError && error.kind === "edit-conflict") {
    return { by: error.problem?.updated_by ?? null, at: error.problem?.updated_at ?? "" };
  }
  return null;
}

/**
 * Text from a document, set apart from the sentence around it, so an Arabic key or
 * title inside an English sentence keeps its own direction. Latin text needs nothing.
 */
export function isolate(text: string): string {
  return /[\u0590-\u08ff\ufb1d-\ufdff\ufe70-\ufeff]/.test(text) ? `\u2068${text}\u2069` : text;
}

/** Today's date where the reader is, as a date field holds it. */
export function today(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}
