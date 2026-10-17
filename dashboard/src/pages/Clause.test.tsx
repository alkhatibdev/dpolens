import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { article13, dpo, signedIn } from "@/test/fixtures";
import type { components } from "@/api/schema";
import { policyClause, retentionVersions } from "@/test/policies";
import { renderAt } from "@/test/render";
import { serve } from "@/test/server";

const KEY = "uae-pdpl:art-13:para-1";
const detail = {
  clause: article13.en[1],
  breadcrumb: [article13.en[0]],
  children: [article13.en[2]],
  cross_references: [],
};
const week = {
  key: KEY,
  days: 7,
  total: 97,
  by_day: [30, 42, 64, 50, 36, 10, 8].map((count, index) => ({
    day: `2026-10-0${index + 3}`,
    count,
  })),
};

function routes(session: unknown) {
  return {
    "GET /v1/sessions/current": { body: session },
    // The client sends the key percent-encoded, colons and all.
    [`GET /v1/clauses/${encodeURIComponent(KEY)}`]: { body: detail },
    [`GET /v1/clauses/${encodeURIComponent(KEY)}/subtree`]: { body: article13.en.slice(1) },
    [`GET /v1/clauses/${encodeURIComponent(KEY)}/activity`]: { body: week },
  };
}

describe("a clause", () => {
  it("says how often it was cited this week, to whoever may read every question", async () => {
    serve(routes(dpo));
    renderAt(`/clauses/${encodeURIComponent(KEY)}`);

    const cited = await screen.findByRole("region", { name: "Cited this week" });
    expect(cited).toHaveTextContent("97");
    expect(screen.getByRole("img", { name: /Cited each day this week: .*64/ })).toBeInTheDocument();
  });

  it("leaves the count out for someone who may not", async () => {
    const { calls } = serve(routes(signedIn));
    renderAt(`/clauses/${encodeURIComponent(KEY)}`);

    await screen.findByText("What your assistant receives");
    expect(screen.queryByRole("region", { name: "Cited this week" })).not.toBeInTheDocument();
    expect(calls.some((call) => call.url.includes("/activity"))).toBe(false);
  });
});

type Detail = components["schemas"]["ClauseInContext"];

describe("a policy's clause read in a version no longer in force", () => {
  const OLD = "data-retention:4.2";
  const second = { label: "2", date: "2026-02-01" };
  const third = { label: "3", date: "2026-11-01" };
  const read: Detail = {
    clause: policyClause(
      {
        key: OLD,
        label: "4.2",
        text: "When the 2 years have passed, a closed account is deleted from live systems within 30 days.",
      },
      second,
    ),
    breadcrumb: [],
    children: [],
    cross_references: [],
    now: {
      key: "data-retention:4.3",
      version_label: "3",
      effective_date: "2026-11-01",
      moved: true,
      changed: false,
    },
    formerly: null,
  };
  const today: Detail = {
    clause: policyClause(
      {
        key: OLD,
        label: "4.2",
        text: "An account closed because of suspected fraud is kept for 5 years after it closes.",
      },
      third,
    ),
    breadcrumb: [],
    children: [],
    cross_references: [],
    now: null,
    formerly: {
      version_label: "2",
      heading: null,
      text: "When the 2 years have passed, a closed account is deleted…",
      now: "data-retention:4.3",
    },
  };
  const versions = {
    slug: "data-retention",
    title: "Data retention policy",
    status: "active",
    versions: [
      { ...retentionVersions.versions[1], number: 3, label: "3", effective_date: third.date },
      {
        ...retentionVersions.versions[1],
        number: 2,
        label: "2",
        state: "replaced",
        until: "2026-10-31",
      },
    ],
  };

  function policyRoutes(answer: Detail | null = null) {
    const asOf = (request: Request) => new URL(request.url).searchParams.has("as_of");
    return serve({
      "GET /v1/sessions/current": { body: dpo },
      [`GET /v1/clauses/${encodeURIComponent(OLD)}`]: (request) => ({
        body: answer ?? (asOf(request) ? read : today),
      }),
      [`GET /v1/clauses/${encodeURIComponent(OLD)}/subtree`]: (request) => ({
        body: [(answer ?? (asOf(request) ? read : today)).clause],
      }),
      [`GET /v1/clauses/${encodeURIComponent(OLD)}/activity`]: {
        body: { key: OLD, days: 7, total: 0, by_day: [] },
      },
      "GET /v1/policies/data-retention/versions": { body: versions },
    });
  }

  it("says when that version was in force, and where the rule is now", async () => {
    policyRoutes();
    renderAt(`/clauses/${encodeURIComponent(OLD)}?as_of=2026-03-01`);

    expect(
      await screen.findByText(
        "You are reading version 2, in force from 1 February 2026 to 31 October 2026.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "In version 3, in force since 1 November 2026, this rule is 4.3, word for word.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Read 4.3 as it stands" })).toHaveAttribute(
      "href",
      `/clauses/${encodeURIComponent("data-retention:4.3")}`,
    );
    const sameKey = (
      await screen.findByRole("heading", { name: "The same key, read today" })
    ).closest("section")!;
    expect(sameKey).toHaveTextContent("An account closed because of suspected fraud");
    expect(sameKey).toHaveTextContent(
      "In version 2, data-retention:4.2 was a different rule, which is 4.3 now:",
    );
  });

  it("says an archived policy's clause still reads, and nothing searches it", async () => {
    policyRoutes({ ...today, clause: { ...today.clause, archived: true }, formerly: null });
    renderAt(`/clauses/${encodeURIComponent(OLD)}`);

    expect(
      await screen.findByText(
        "Data retention policy is archived. Nothing searches it, and its clauses still read, so a citation of one can be checked.",
      ),
    ).toBeInTheDocument();
  });
});
