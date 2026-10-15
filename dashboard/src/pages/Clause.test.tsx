import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { article13, dpo, signedIn } from "@/test/fixtures";
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
