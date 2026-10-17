import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { dpo, retentionComparison, retentionVersions } from "@/test/policies";
import { renderAt } from "@/test/render";
import { serve } from "@/test/server";

function routes() {
  return serve({
    "GET /v1/sessions/current": { body: dpo },
    "GET /v1/policies/data-retention/versions": { body: retentionVersions },
    "GET /v1/policies/data-retention/compare": { body: retentionComparison },
  });
}

describe("comparing two versions", () => {
  it("starts with the version before the one in force, and marks the words that changed", async () => {
    const { calls } = routes();
    renderAt("/library/data-retention/compare");

    expect(await screen.findByRole("heading", { name: "Compare versions" })).toBeInTheDocument();
    const asked = new URL(calls.find((call) => call.url.includes("/compare"))!.url);
    expect([asked.searchParams.get("from"), asked.searchParams.get("to")]).toEqual(["1", "2"]);

    expect(await screen.findByText("Nothing in version 2 continues it")).toBeInTheDocument();
    expect(screen.getByText("2", { selector: "ins" })).toBeInTheDocument();
    expect(screen.getByText("3", { selector: "del" })).toBeInTheDocument();
    expect(
      screen.getByText("A citation of version 1's 4.4 says the rule was removed."),
    ).toBeInTheDocument();
    expect(screen.getByText("The same in both versions · 1")).toBeInTheDocument();
  });

  it("compares the versions chosen", async () => {
    const { calls } = routes();
    renderAt("/library/data-retention/compare");
    await screen.findByText("Nothing in version 2 continues it");

    await userEvent.click(screen.getByRole("button", { name: /^Compare to: Version 2/ }));
    const menu = screen.getByRole("menu");
    await userEvent.click(within(menu).getByRole("menuitemradio", { name: /^Version 1/ }));

    // A version compared with itself has nothing to show, and nothing is asked.
    expect(await screen.findByText("The two versions are the same, clause for clause."));
    expect(calls.filter((call) => call.url.includes("/compare"))).toHaveLength(1);
  });
});
