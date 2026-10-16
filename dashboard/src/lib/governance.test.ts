import { describe, expect, it } from "vitest";

import i18n from "@/i18n";
import { entry } from "@/test/fixtures";

import { describeEntry } from "./governance";

const t = i18n.t.bind(i18n);

function sentence(action: string, details: Record<string, unknown>): string {
  return describeEntry(
    t,
    entry({ seq: 1, action, target_type: "document_version", details: { ...details, via: "cli" } }),
  );
}

const retention = { document: "retention", title: "Retention policy" };

describe("a policy's entries in the governance log", () => {
  it("say what was uploaded and accepted, naming the policy by its title", () => {
    expect(sentence("document.drafted", { ...retention, file: "retention-v2.md" })).toBe(
      "Uploaded retention-v2.md, a draft of Retention policy",
    );
    expect(
      sentence("document.flag_accepted", {
        ...retention,
        flags: [{ position: 1 }, { position: 2 }],
      }),
    ).toBe("Accepted 2 flags in the draft of Retention policy");
  });

  it("give the version published and the day it takes effect", () => {
    const published = { ...retention, version: "2", effective_date: "2026-06-01" };
    expect(sentence("document.published", { ...published, restored: false })).toBe(
      "Published version 2 of Retention policy, in force from 1 June 2026",
    );
    expect(sentence("document.published", { ...published, restored: true })).toContain(
      "brought it back from the archive",
    );
  });

  it("tell a replaced draft from a discarded one", () => {
    expect(
      sentence("document.draft_discarded", { ...retention, reason: "replaced by a new upload" }),
    ).toBe("Replaced the draft of Retention policy with a new upload");
    expect(sentence("document.draft_discarded", { ...retention, reason: "discarded" })).toBe(
      "Discarded the draft of Retention policy",
    );
  });

  it("fall back to the slug when an entry has no title", () => {
    expect(sentence("document.archived", { document: "retention" })).toBe("Archived retention");
  });
});
