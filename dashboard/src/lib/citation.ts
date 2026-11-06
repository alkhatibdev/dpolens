import type { Clause } from "@/api/client";

import { languageName } from "./format";

/**
 * The same one-line citation the MCP server gives an assistant, built from the
 * clause's own fields, so a citation reads the same wherever it was copied.
 */
export function citationFor(clause: Clause, breadcrumb: readonly Clause[] = []): string {
  const trail = breadcrumb.map(namesOf).filter(Boolean);
  const where = [...trail, namesOf(clause) || clause.key].join(" > ");
  const version = clause.version_label ?? "unversioned";
  let citation = `${clause.document_title}, ${where} (${clause.key}), version ${version}, ${inForce(clause)}`;
  const prevails = prevailingLanguage(clause);
  if (prevails) {
    citation += `. A translation: where the texts differ, the ${languageName(prevails)} text prevails`;
  }
  return citation;
}

/** When the text applies, worded as the MCP server's citation words it. */
export function inForce(clause: Clause, asOf: string = new Date().toISOString().slice(0, 10)) {
  const since = clause.in_force_from;
  const until = clause.in_force_until;
  if (clause.in_force) {
    return `in force since ${since}${until ? `, until ${until}` : ""}`;
  }
  if (until && until <= asOf) {
    return `no longer in force since ${until}`;
  }
  if (!since) {
    return "not in force yet: no date set";
  }
  return `in force from ${since}${until ? ` until ${until}` : ""}`;
}

/** The text and its citation, as somebody pastes it into a review or a comment. */
export function quotationFor(clause: Clause, breadcrumb: readonly Clause[] = []): string {
  return `${clause.text}\n\n${citationFor(clause, breadcrumb)}`;
}

/** The language to rely on, when the clause in hand is a translation. */
export function prevailingLanguage(clause: Clause): string | null {
  return clause.is_authoritative ? null : (clause.authoritative_language ?? null);
}

/** What a clause is called: its heading, or the numbering the document uses. */
export function namesOf(clause: Pick<Clause, "heading" | "label">): string {
  const heading = (clause.heading ?? "").trim();
  const label = (clause.label ?? "").trim().replace(/\.$/, "");
  return heading && label ? `${label} ${heading}` : heading || label;
}
