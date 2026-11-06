import type { LoggedClause } from "@/api/client";

/**
 * A name in `lang`, else in English, which every law is named in, else the one name a
 * policy has, in its own language.
 */
export function inLanguage(byLanguage: Readonly<Record<string, string>>, lang = "en"): string {
  return byLanguage[lang] ?? byLanguage.en ?? Object.values(byLanguage)[0] ?? "";
}

/** "GDPR", "UAE PDPL": a law by what people call it, or a policy by its own title. */
export function sourceName(
  shortName: Readonly<Record<string, string>> | null | undefined,
  title: string,
  lang = "en",
): string {
  return shortName ? inLanguage(shortName, lang) : title;
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
