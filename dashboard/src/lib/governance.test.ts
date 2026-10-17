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

  it("say which match a reviewer said was wrong", () => {
    expect(
      sentence("document.match_rejected", {
        ...retention,
        key: "retention:4.3",
        earlier: "retention:4.2",
        previous: "2",
      }),
    ).toBe("Said 4.3 in the draft of Retention policy is a different rule from version 2's 4.2");
  });

  it("say which match a reviewer made", () => {
    expect(
      sentence("document.match_made", {
        ...retention,
        key: "retention:4.4",
        earlier: "retention:4.3",
        previous: "2",
      }),
    ).toBe("Said 4.4 in the draft of Retention policy is the same rule as version 2's 4.3");
  });

  it("say how a clause was fixed", () => {
    expect(
      sentence("document.clause_fixed", {
        ...retention,
        edit: "move-under",
        key: "retention:personal-use",
        with: "retention:3",
      }),
    ).toBe("Moved personal-use under 3 in the draft of Retention policy");
    expect(
      sentence("document.clause_fixed", {
        ...retention,
        edit: "split",
        key: "retention:4.1",
        with: "retention:4.2",
      }),
    ).toBe("Split 4.1 in the draft of Retention policy, making 4.2");
  });

  it("fall back to the slug when an entry has no title", () => {
    expect(sentence("document.archived", { document: "retention" })).toBe("Archived retention");
  });
});

describe("a law's entries in the governance log", () => {
  it("say which version of which law was loaded, and where it came from", () => {
    const loaded = { pack: "uae-pdpl", version: "2026.2" };
    expect(
      sentence("laws.pack_loaded", {
        ...loaded,
        source: "update",
        repository: "alkhatibdev/dpolens",
      }),
    ).toBe("Loaded UAE PDPL 2026.2, downloaded from alkhatibdev/dpolens on GitHub");
    expect(sentence("laws.pack_loaded", { ...loaded, source: "file" })).toBe(
      "Loaded UAE PDPL 2026.2, imported from a file",
    );
    expect(sentence("laws.pack_loaded", { ...loaded, source: "image" })).toBe(
      "Loaded UAE PDPL 2026.2, which came with this instance",
    );
  });

  it("still say what was loaded when the source is new to this build", () => {
    expect(
      sentence("laws.pack_loaded", { pack: "gdpr", version: "2026.1", source: "mirror" }),
    ).toBe("Loaded GDPR 2026.1");
  });
});
