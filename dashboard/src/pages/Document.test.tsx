import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { PolicyFile } from "@/api/policies";
import {
  dpo,
  policies,
  policyClause,
  retentionDocument,
  retentionPart,
  retentionVersions,
} from "@/test/policies";
import { renderAt } from "@/test/render";
import { serve } from "@/test/server";

const FIRST = { label: "1", date: "2025-09-01" };

const file: PolicyFile = {
  slug: "data-retention",
  number: 2,
  status: "published",
  source: { name: "data-retention.docx", format: "docx", size: 40_960 },
  paragraphs: [
    ["4. Retention periods", "data-retention:4"],
    [retentionPart[1]?.text ?? "", "data-retention:4.1"],
    ["5. Review", "data-retention:5"],
  ].map(([text, clause], position) => ({
    position,
    text: text ?? "",
    place: "body",
    heading: null,
    title: false,
    label: null,
    bold: false,
    table: null,
    row: null,
    cell: null,
    header: false,
    clause: clause ?? null,
    clauses: clause ? [clause] : [],
    set_aside: null,
  })),
};

/** The library's answers, which read the version in force unless asked for another day. */
function library() {
  const older = (request: Request) => new URL(request.url).searchParams.get("as_of") !== null;
  return serve({
    "GET /v1/sessions/current": { body: dpo },
    "GET /v1/policies": { body: policies },
    "GET /v1/documents/data-retention": (request) => ({
      body: older(request)
        ? {
            ...retentionDocument,
            document: {
              ...retentionDocument.document,
              version_label: "1",
              effective_date: "2025-09-01",
            },
          }
        : retentionDocument,
    }),
    [`GET /v1/clauses/${encodeURIComponent("data-retention:4")}/subtree`]: (request) => ({
      body: older(request)
        ? retentionPart.map((clause) =>
            policyClause({ ...clause, text: clause.text.replace("2 years", "3 years") }, FIRST),
          )
        : retentionPart,
    }),
    "GET /v1/policies/data-retention/versions": { body: retentionVersions },
    "GET /v1/policies/data-retention/versions/2/file": { body: file },
  });
}

describe("a policy in the library", () => {
  it("shows its versions, the draft to a reviewer, and its original", async () => {
    library();
    renderAt("/library/data-retention");

    expect(await screen.findByText("Your policy")).toBeInTheDocument();
    expect(screen.getByText("In force since 1 February 2026")).toBeInTheDocument();
    const draft = screen.getByRole("note");
    expect(draft).toHaveTextContent("Version 3 is a draft, with 3 flags to settle.");
    expect(within(draft).getByRole("link", { name: "Continue the review" })).toHaveAttribute(
      "href",
      "/policies/data-retention/draft",
    );
    expect(screen.getByRole("link", { name: "Download the original" })).toHaveAttribute(
      "href",
      "/v1/policies/data-retention/versions/2/original",
    );

    const versions = await screen.findByRole("region", { name: "Versions" });
    const rows = within(versions).getAllByRole("listitem");
    expect(rows[1]).toHaveTextContent("In force");
    expect(rows[1]).toHaveTextContent("Since 1 February 2026");
    expect(rows[2]).toHaveTextContent("1 September 2025 to 31 January 2026");
    expect(rows[2]).toHaveTextContent("Published 25 August 2025 by Yousef Haddad");
    expect(within(versions).getByRole("link", { name: "Read version 1" })).toHaveAttribute(
      "href",
      "/library/data-retention?as_of=2025-09-01",
    );
    expect(
      within(versions).getByRole("link", { name: "Download the original of version 1" }),
    ).toHaveAttribute("href", "/v1/policies/data-retention/versions/1/original");
    expect(within(versions).getByRole("link", { name: "Compare versions" })).toHaveAttribute(
      "href",
      "/library/data-retention/compare",
    );
  });

  it("reads an older version as it stood, and says until when it was in force", async () => {
    library();
    renderAt("/library/data-retention?as_of=2025-09-01");

    const banner = await screen.findByText(
      "You are reading version 1, in force from 1 September 2025 to 31 January 2026.",
    );
    expect(banner.closest("[role='note']")).not.toBeNull();
    expect(screen.getByRole("link", { name: "Read the version in force" })).toHaveAttribute(
      "href",
      "/library/data-retention",
    );
    expect(await screen.findByText(/for 3 years after it closes/)).toBeInTheDocument();
  });

  it("shows the file as read beside the part chosen", async () => {
    library();
    renderAt("/library/data-retention");

    await userEvent.click(await screen.findByRole("button", { name: "Beside the file" }));

    const lit = await screen.findByText(retentionPart[1]?.text ?? "");
    expect(lit.closest("[data-lit]")).not.toBeNull();
    expect(screen.getByText("5. Review").closest("[data-lit]")).toBeNull();
  });
});
