import type { SignedIn } from "@/api/client";
import type {
  DraftClause,
  DraftFlag,
  FileParagraph,
  PolicyDraft,
  PolicyFile,
  PolicySummary,
  PolicyVersion,
} from "@/api/policies";

import { admin } from "./fixtures";

/** Acme's DPO, who uploads, reviews and publishes the policies. */
export const dpo: SignedIn = {
  ...admin,
  account: {
    id: "9a1c3e5f-2b4d-4f6a-8c0e-1d3f5a7b9c2e",
    email: "mariam@example.com",
    display_name: "Mariam Al Amiri",
    roles: ["DPO"],
  },
  permissions: [
    "documents.read",
    "documents.upload",
    "documents.publish",
    "governance.read",
    "queries.read_all",
  ],
};

export function summary(
  fields: Partial<PolicySummary> & Pick<PolicySummary, "slug" | "title">,
): PolicySummary {
  return {
    status: "active",
    in_force: null,
    in_force_since: null,
    published: 0,
    draft: null,
    indexing: null,
    in_force_number: null,
    next_label: "1",
    sample: false,
    scheduled: null,
    review: null,
    last_change: null,
    ...fields,
  };
}

const NOW = new Date().toISOString();

export const retentionSummary = summary({
  slug: "data-retention",
  title: "Data retention policy",
  in_force: "2",
  in_force_since: "2026-02-01",
  in_force_number: 2,
  next_label: "3",
  published: 2,
  indexing: "succeeded",
  draft: 3,
  review: {
    flags: 3,
    open: 3,
    uploaded_by: "Mariam Al Amiri",
    uploaded_at: NOW,
    next_label: "3",
  },
  last_change: { by: "Mariam Al Amiri", at: NOW },
});

export const policies: PolicySummary[] = [
  retentionSummary,
  summary({
    slug: "acceptable-use",
    title: "Acceptable use policy",
    draft: 1,
    review: {
      flags: 2,
      open: 0,
      uploaded_by: "Mariam Al Amiri",
      uploaded_at: NOW,
      next_label: "1",
    },
    last_change: { by: "Mariam Al Amiri", at: NOW },
  }),
  summary({
    slug: "information-security",
    title: "Information security policy",
    in_force: "2",
    in_force_since: "2026-01-15",
    in_force_number: 2,
    published: 3,
    scheduled: { label: "3", effective_date: "2026-11-01" },
    last_change: { by: "Yousef Haddad", at: "2026-10-02T10:00:00Z" },
  }),
  summary({
    slug: "sample-data-protection",
    title: "Sample data protection policy",
    status: "archived",
    in_force: "1",
    in_force_since: "2026-01-01",
    in_force_number: 1,
    published: 1,
    sample: true,
    last_change: { by: null, at: "2026-09-04T08:00:00Z" },
  }),
];

export function clause(
  fields: Partial<DraftClause> & Pick<DraftClause, "key" | "text">,
): DraftClause {
  return {
    kind: "paragraph",
    label: null,
    heading: null,
    lang: "en",
    layer: "numbering",
    change: null,
    continues: null,
    earlier: null,
    children: [],
    ...fields,
  };
}

export function flag(
  fields: Partial<DraftFlag> & Pick<DraftFlag, "position" | "kind" | "detail">,
): DraftFlag {
  return {
    key: null,
    accepted_by: null,
    accepted_at: null,
    resolved_by: null,
    resolved_at: null,
    resolution: null,
    paragraph: null,
    ...fields,
  };
}

function version(
  fields: Partial<PolicyVersion> & Pick<PolicyVersion, "slug" | "title" | "number">,
): PolicyVersion {
  return {
    label: null,
    status: "draft",
    effective_date: "2026-11-01",
    source: { name: `${fields.slug}.docx`, format: "docx", size: 49_152 },
    created_at: NOW,
    created_by: "Mariam Al Amiri",
    published_at: null,
    published_by: null,
    indexing: null,
    ...fields,
  };
}

const DELETED =
  "When the 2 years have passed, a closed account is deleted from live systems within 30 days, and from backups when those backups expire.";
const PAYMENTS = "Payment records are kept for 7 years, as tax law requires.";

/** Version 3 of the retention policy: a fraud rule at 4.2 moves the two rules after it. */
export const retentionDraft: PolicyDraft = {
  version: version({
    slug: "data-retention",
    title: "Data retention policy",
    number: 3,
    source: { name: "data-retention-2026-10.docx", format: "docx", size: 63_488 },
  }),
  clauses: [
    clause({
      key: "data-retention:4",
      kind: "section",
      label: "4",
      heading: "Retention periods",
      text: "",
      layer: "native_structure",
      change: "unchanged",
      continues: "data-retention:4",
      children: [
        clause({
          key: "data-retention:4.1",
          label: "4.1",
          text: "Customer account data is kept while the account is open and for 2 years after it closes.",
          change: "unchanged",
          continues: "data-retention:4.1",
        }),
        clause({
          key: "data-retention:4.2",
          label: "4.2",
          text: "An account closed because of suspected fraud is kept for 5 years after it closes, so that an investigation can be completed.",
          change: "added",
        }),
        clause({
          key: "data-retention:4.3",
          label: "4.3",
          text: DELETED,
          change: "moved",
          continues: "data-retention:4.2",
          earlier: { key: "data-retention:4.2", label: "4.2", heading: null, text: DELETED },
        }),
        clause({
          key: "data-retention:4.4",
          label: "4.4",
          text: "Payment records are kept for 7 years after the end of the financial year, as tax law requires.",
          change: "moved",
          continues: "data-retention:4.3",
          earlier: { key: "data-retention:4.3", label: "4.3", heading: null, text: PAYMENTS },
        }),
      ],
    }),
  ],
  flags: [
    flag({
      position: 1,
      kind: "unmatched_key",
      key: "data-retention:4.2",
      detail:
        "In version 2, 4.2 was a different rule (When the 2 years have passed, a closed account is deleted…), now 4.3.",
    }),
    flag({
      position: 2,
      kind: "unmatched_key",
      key: "data-retention:4.3",
      detail: "4.3 continues 4.2 from version 2, renumbered. Check that it is the same rule.",
    }),
    flag({
      position: 3,
      kind: "unmatched_key",
      key: "data-retention:4.4",
      detail:
        "4.4 continues 4.3 from version 2, renumbered and reworded. Check that it is the same rule.",
    }),
  ],
  coverage: { characters: 1_160, in_clauses: 1_100, set_aside: 60, missed: 0 },
  set_aside: [{ reason: "title", text: "Data retention policy" }],
  notices: [],
  previous: "2",
  removed: [],
  changes: { added: 1, modified: 0, moved: 2, unchanged: 2, removed: 0 },
  revision: 3,
  updated_at: NOW,
  updated_by: "Mariam Al Amiri",
  next_label: "3",
};

/** The first version of the acceptable use policy, with two flags from how it was read. */
export const acceptableUseDraft: PolicyDraft = {
  ...retentionDraft,
  version: version({
    slug: "acceptable-use",
    title: "Acceptable use policy",
    number: 1,
    source: { name: "acceptable-use-policy.docx", format: "docx", size: 49_152 },
  }),
  clauses: [
    clause({
      key: "acceptable-use:3",
      kind: "section",
      label: "3",
      heading: "Using Acme systems",
      text: "",
      layer: "native_structure",
      children: [
        clause({
          key: "acceptable-use:3.2",
          label: "3.2",
          text: "Lock your screen whenever you leave your desk.",
          fixes: ["make-heading", "move-out"],
        }),
        clause({
          key: "acceptable-use:3.4",
          label: "3.4",
          text: "Never copy customer data to a personal device or a personal email account.",
          fixes: ["merge", "make-heading", "move-under", "move-out"],
        }),
      ],
    }),
    clause({
      key: "acceptable-use:personal-use",
      kind: "section",
      heading: "Personal use:",
      text: "",
      layer: "typography",
      fixes: ["merge", "make-text", "move-under"],
      children: [
        clause({
          key: "acceptable-use:personal-use:p1",
          text: "Occasional personal use is allowed, as long as no customer data is involved.",
          layer: "native_structure",
          fixes: ["make-heading", "move-out"],
        }),
      ],
    }),
    clause({
      key: "acceptable-use:4",
      kind: "section",
      label: "4",
      heading: "Monitoring",
      text: "",
      layer: "native_structure",
      fixes: ["merge", "make-text", "move-under"],
      children: [
        clause({
          key: "acceptable-use:4.1",
          label: "4.1",
          text: "Acme records who opens systems that hold personal data, to detect misuse. 4.2 The records are kept for 90 days.",
          fixes: ["split", "make-heading", "move-out"],
          splits: [{ at: 74, label: "4.2" }],
        }),
      ],
    }),
  ],
  flags: [
    flag({
      position: 1,
      kind: "low_confidence_boundary",
      key: "acceptable-use:personal-use",
      detail:
        '"Personal use:" has no number, unlike the headings around it, so it may belong under the one before it.',
      suggestion: { edit: "move-under", key: "acceptable-use:personal-use", at: null },
    }),
    flag({
      position: 2,
      kind: "numbering_gap",
      key: "acceptable-use:3.4",
      detail: "3.4 follows 3.2.",
    }),
  ],
  previous: null,
  changes: { added: 0, modified: 0, moved: 0, unchanged: 0, removed: 0 },
  revision: 1,
  next_label: "1",
};

function line(
  fields: Partial<FileParagraph> & Pick<FileParagraph, "position" | "text">,
): FileParagraph {
  return {
    place: "body",
    heading: null,
    title: false,
    label: null,
    bold: false,
    table: null,
    row: null,
    cell: null,
    header: false,
    clause: null,
    set_aside: null,
    ...fields,
  };
}

export const acceptableUseFile: PolicyFile = {
  slug: "acceptable-use",
  number: 1,
  status: "draft",
  source: { name: "acceptable-use-policy.docx", format: "docx", size: 49_152 },
  paragraphs: [
    line({ position: 0, text: "Acceptable Use Policy", title: true, set_aside: "title" }),
    line({
      position: 1,
      text: "Contents: 1 Purpose · 3 Using Acme systems",
      set_aside: "contents",
    }),
    line({ position: 2, text: "3. Using Acme systems", heading: 1, clause: "acceptable-use:3" }),
    line({
      position: 3,
      text: "3.2 Lock your screen whenever you leave your desk.",
      clause: "acceptable-use:3.2",
    }),
    line({
      position: 4,
      text: "3.4 Never copy customer data to a personal device or a personal email account.",
      clause: "acceptable-use:3.4",
    }),
    line({
      position: 5,
      text: "Personal use:",
      bold: true,
      clause: "acceptable-use:personal-use",
    }),
    line({
      position: 6,
      text: "Occasional personal use is allowed, as long as no customer data is involved.",
      clause: "acceptable-use:personal-use:p1",
    }),
    line({ position: 7, text: "4. Monitoring", heading: 1, clause: "acceptable-use:4" }),
    line({
      position: 8,
      text: "4.1 Acme records who opens systems that hold personal data, to detect misuse. 4.2 The records are kept for 90 days.",
      clause: "acceptable-use:4.1",
    }),
  ],
};
