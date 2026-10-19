import type { Clause } from "@/api/client";
import { isRightToLeft } from "@/lib/format";
import { cn } from "@/lib/utils";

import { KeyButton } from "./CopyCitation";

/** The clauses above one, inside what is shown, for its citation. */
function ancestorsOf(clauses: readonly Clause[], index: number): Clause[] {
  const trail: Clause[] = [];
  let depth = clauses[index]?.depth ?? 0;
  for (let at = index - 1; at >= 0; at -= 1) {
    const clause = clauses[at];
    if (clause && clause.depth < depth) {
      trail.unshift(clause);
      depth = clause.depth;
    }
  }
  return trail;
}

/**
 * A clause and its points in the one language being read, each with its key beside
 * it; on a phone, the key above.
 */
export function Reading({
  clauses,
  breadcrumb,
}: {
  clauses: readonly Clause[];
  /** The clauses above the first one shown, for the citations. */
  breadcrumb: readonly Clause[];
}) {
  // Every clause counts for a citation's trail; only those with words get a row.
  const base = clauses.find((clause) => clause.text.trim())?.depth ?? 0;

  return (
    <div>
      {clauses.map((clause, index) => {
        if (!clause.text.trim()) {
          return null;
        }
        const rtl = isRightToLeft(clause.lang);
        const leads = (clauses[index + 1]?.depth ?? -1) > clause.depth;
        return (
          <div
            key={clause.key}
            id={clause.key}
            className="flex scroll-mt-24 flex-col gap-2 border-b border-line py-3.5 last:border-b-0 md:grid md:grid-cols-[minmax(0,1fr)_76px] md:items-start md:gap-x-[18px] md:gap-y-0"
          >
            <p
              lang={clause.lang}
              dir={rtl ? "rtl" : "ltr"}
              style={{ paddingInlineStart: Math.max(0, clause.depth - base) * 18 }}
              className={cn(
                "text-[15px] leading-relaxed sm:text-base",
                rtl && "text-[16px] sm:text-[17px]",
                leads && "font-medium",
              )}
            >
              {clause.label ? <span className="font-semibold">{clause.label} </span> : null}
              {clause.text}
            </p>
            <div className="order-first flex md:order-none md:justify-center">
              <KeyButton
                clause={clause}
                breadcrumb={[...breadcrumb, ...ancestorsOf(clauses, index)]}
                label={clause.key.split(":").pop() ?? clause.key}
                emphasis={clause.depth === base}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}
