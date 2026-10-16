import { describe, expect, it } from "vitest";

import { isolate, prefixFrom } from "./policies";
import { wordDiff } from "./wordDiff";

describe("wordDiff", () => {
  it("marks the words a new version adds", () => {
    expect(
      wordDiff(
        "Payment records are kept for 7 years, as tax law requires.",
        "Payment records are kept for 7 years after the end of the financial year, as tax law requires.",
      ),
    ).toEqual([
      { text: "Payment records are kept for 7 years", change: "same" },
      { text: " after the end of the financial year", change: "added" },
      { text: ", as tax law requires.", change: "same" },
    ]);
  });

  it("marks the words it takes away", () => {
    expect(wordDiff("kept for 5 years", "kept for 6 years")).toEqual([
      { text: "kept for", change: "same" },
      { text: " 5", change: "removed" },
      { text: " 6", change: "added" },
      { text: " years", change: "same" },
    ]);
  });

  it("leaves the same words as they are", () => {
    expect(wordDiff("تُحفظ السجلات", "تُحفظ  السجلات")).toEqual([
      { text: "تُحفظ السجلات", change: "same" },
    ]);
  });
});

describe("prefixFrom", () => {
  it("makes a key prefix from a file's name", () => {
    expect(prefixFrom("Data Retention (2026).docx")).toBe("data-retention-2026");
    expect(prefixFrom("politique-de-sécurité.md")).toBe("politique-de-securite");
  });

  it("leaves it to the person when the name has no Latin letters", () => {
    expect(prefixFrom("سياسة-حماية-البيانات.docx")).toBe("");
  });
});

describe("isolate", () => {
  it("keeps an Arabic number's direction inside an English sentence", () => {
    expect(isolate("المادة (2)")).toBe("\u2068المادة (2)\u2069");
  });

  it("leaves Latin text as it is", () => {
    expect(isolate("4.2")).toBe("4.2");
  });
});
