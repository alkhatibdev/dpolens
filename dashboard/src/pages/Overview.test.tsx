import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { dpo, overview, signedIn, uae } from "@/test/fixtures";
import { policies, retentionDocument } from "@/test/policies";
import { renderAt } from "@/test/render";
import { serve } from "@/test/server";

describe("the overview", () => {
  it("shows the week in numbers, and nobody's name", async () => {
    const { calls } = serve({
      "GET /v1/sessions/current": { body: dpo },
      "GET /v1/overview": { body: overview },
    });
    renderAt("/overview");

    expect(await screen.findByText("1,284")).toBeInTheDocument();
    expect(screen.getByText("18% more than the 7 days before")).toBeInTheDocument();
    expect(screen.getByText("94%", { selector: "div" })).toBeInTheDocument();
    expect(screen.getByText("77 found nothing in force")).toBeInTheDocument();
    expect(screen.getByText("GDPR, UAE PDPL")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Questions by day: .*Today 214/ })).toBeInTheDocument();
    const cited = screen.getByRole("link", { name: /gdpr:art-17:para-1/ });
    expect(cited).toHaveTextContent("GDPR · Article 17(1), Right to erasure");
    const unanswered = screen.getByRole("heading", { name: "Found nothing" }).closest("section")!;
    expect(
      within(unanswered).getByText("retention period for CCTV footage in the warehouse"),
    ).toBeInTheDocument();
    const asked = new URL(calls.find((call) => call.url.includes("/v1/overview"))!.url);
    expect(asked.searchParams.get("days")).toBe("7");
    expect(asked.searchParams.get("tz")).toBeTruthy();
  });

  it("sends someone who may not read every question to the library", async () => {
    serve({
      "GET /v1/sessions/current": { body: signedIn },
      "GET /v1/documents": { body: { documents: [uae], total: 1, limit: 100, offset: 0 } },
    });
    const { router } = renderAt("/");

    await screen.findByRole("heading", { name: "Library" });
    expect(router.state.location.pathname).toBe("/library");
  });

  it("lands someone who may read every question on the overview", async () => {
    serve({
      "GET /v1/sessions/current": { body: dpo },
      "GET /v1/overview": { body: overview },
    });
    const { router } = renderAt("/");

    await screen.findByRole("heading", { name: "Overview" });
    expect(router.state.location.pathname).toBe("/overview");
  });

  it("counts the policies in force and lists the drafts waiting for review, naming nobody", async () => {
    serve({
      "GET /v1/sessions/current": { body: dpo },
      "GET /v1/overview": { body: overview },
      "GET /v1/documents": {
        body: { documents: [uae, retentionDocument.document], total: 2, limit: 100, offset: 0 },
      },
      "GET /v1/policies": { body: policies },
    });
    renderAt("/overview");

    const tile = (await screen.findByText("Policies in force")).closest("div.relative")!
      .parentElement as HTMLElement;
    expect(tile).toHaveTextContent("1");
    expect(tile).toHaveTextContent("2 drafts waiting for review");
    const waiting = screen.getByRole("heading", { name: "Waiting for review" }).closest("section")!;
    expect(within(waiting).getByText("Data retention policy, version 3")).toBeInTheDocument();
    expect(within(waiting).getByText("3 flags to settle")).toBeInTheDocument();
    expect(within(waiting).getByText("Ready to publish")).toBeInTheDocument();
    expect(
      within(waiting).getAllByRole("link", { name: "Continue the review" })[0],
    ).toHaveAttribute("href", "/policies/data-retention/draft");
    expect(waiting).not.toHaveTextContent("Mariam");
    expect(screen.getByRole("button", { name: "Upload a policy" })).toBeInTheDocument();
  });
});
