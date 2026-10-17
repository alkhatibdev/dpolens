import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { SIGN_IN_CLAUSES } from "./signInClauses";

const PACKS = resolve(dirname(fileURLToPath(import.meta.url)), "../../../packs");

function pack(file: string): string {
  return readFileSync(resolve(PACKS, file), "utf8");
}

/** One numbered paragraph of a pack's article, from its heading to the next one. */
function paragraph(file: string, number: number): string {
  const text = pack(file);
  const start = text.indexOf(`{#para-${number}}`);
  const end = text.indexOf(`{#para-${number + 1}}`);
  expect(start).toBeGreaterThan(-1);
  return text.slice(start, end === -1 ? undefined : end);
}

describe("the clauses the sign-in pages quote", () => {
  it("are word for word what the packs hold, at the keys they are shown with", () => {
    const { gdpr, uae } = SIGN_IN_CLAUSES;
    expect(gdpr.key).toBe("gdpr:art-17:para-1:pt-a");
    expect(paragraph("gdpr/gdpr/art-17.md", 1)).toContain(`{#pt-a}\n\n${gdpr.text}\n`);
    expect(uae.key).toBe("uae-pdpl:art-15:para-2:pt-a");
    expect(paragraph("uae-pdpl/uae-pdpl/art-15.md", 2)).toContain(`{#pt-a}\n\n${uae.text}\n`);
  });

  it("carry the version and the dates the packs record", () => {
    expect(pack("gdpr/pack.yaml")).toContain(`version: "${SIGN_IN_CLAUSES.gdpr.version}"`);
    expect(pack("gdpr/pack.yaml")).toContain(`effective_date: ${SIGN_IN_CLAUSES.gdpr.effective}`);
    expect(pack("uae-pdpl/pack.yaml")).toContain(
      `effective_date: ${SIGN_IN_CLAUSES.uae.effective}`,
    );
  });
});
