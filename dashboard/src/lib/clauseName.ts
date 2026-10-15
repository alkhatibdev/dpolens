import type { LoggedClause } from "@/api/client";

/** "GDPR", "UAE PDPL": a law by its pack, or a policy by its own title. */
export function sourceName(packSlug: string | null | undefined, title: string): string {
  return packSlug ? packSlug.toUpperCase().replace(/-/g, " ") : title;
}

/** "Article 17(1)(e)": the numbering a lawyer cites, from the outermost label down. */
export function numbering(clause: LoggedClause): string {
  const labels = clause.trail
    .map((step) => (step.label ?? "").trim().replace(/\.$/, ""))
    .filter(Boolean);
  const [first, ...rest] = labels;
  if (!first) {
    return clause.key;
  }
  return first + rest.map((label) => (label.startsWith("(") ? label : `(${label})`)).join("");
}

/** The heading of the article a clause sits in, when it has one. */
export function headingOf(clause: LoggedClause): string | null {
  return clause.trail.find((step) => step.heading)?.heading ?? null;
}
