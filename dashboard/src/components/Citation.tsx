import type { LoggedClause } from "@/api/client";
import { headingOf, numbering, sourceName } from "@/lib/clauseName";

/**
 * "GDPR · Article 17(1), Right to erasure". The numbering and the heading each keep
 * their own direction, so an Arabic label reads correctly inside an English line.
 */
export function Citation({ clause, heading = false }: { clause: LoggedClause; heading?: boolean }) {
  const title = heading ? headingOf(clause) : null;
  return (
    <>
      {sourceName(clause.pack_slug, clause.document_title)} · <bdi>{numbering(clause)}</bdi>
      {title ? (
        <>
          , <bdi>{title}</bdi>
        </>
      ) : null}
    </>
  );
}
