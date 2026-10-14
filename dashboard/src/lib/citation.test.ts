import { describe, expect, it } from "vitest";

import { article13 } from "@/test/fixtures";

import { citationFor, quotationFor } from "./citation";

const [article, paragraph] = article13.en;

describe("a citation", () => {
  it("is the line the MCP server gives an assistant, word for word", () => {
    expect(citationFor({ ...paragraph!, is_authoritative: false }, [article!])).toBe(
      "Federal Decree by Law No. (45) of 2021 Concerning the Protection of Personal Data, " +
        "Article (13) Right to Receive Information > 1 (uae-pdpl:art-13:para-1), " +
        "version 2026.1, in force since 2022-01-02. " +
        "A translation: where the texts differ, the Arabic text prevails",
    );
  });

  it("says nothing about a translation when the text is the one that prevails", () => {
    expect(citationFor({ ...paragraph!, is_authoritative: true }, [article!])).not.toContain(
      "translation",
    );
  });

  it("is copied under the text it cites", () => {
    const quotation = quotationFor(paragraph!, [article!]);
    expect(quotation.startsWith(paragraph!.text)).toBe(true);
    expect(quotation).toContain("(uae-pdpl:art-13:para-1)");
  });
});
