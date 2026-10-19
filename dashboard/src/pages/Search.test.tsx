import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { SearchResult } from "@/api/client";
import { admin, article13, signedIn, uae } from "@/test/fixtures";
import { renderAt } from "@/test/render";
import { serve } from "@/test/server";

const result: SearchResult = {
  clause: {
    ...article13.en[1]!,
    is_authoritative: false,
    authoritative_text: article13.ar[1]!.text,
  },
  score: 0.9,
  breadcrumb: [article13.en[0]!],
  cross_references: [],
  expanded: [],
  ranks: null,
};

describe("search results", () => {
  it("shows each clause with its key, where it sits and the text that prevails", async () => {
    const { calls } = serve({
      "GET /v1/sessions/current": { body: signedIn },
      "GET /v1/documents": { body: { documents: [uae], total: 1, limit: 100, offset: 0 } },
      "POST /v1/search": { body: { laws: ["uae-pdpl"], results: [result] } },
    });
    renderAt("/search?q=Can%20a%20user%20see%20their%20data%3F");

    const card = (await screen.findByText("uae-pdpl:art-13:para-1")).closest("article")!;
    expect(
      within(card).getByText(/Article \(13\) Right to Receive Information/),
    ).toBeInTheDocument();
    expect(within(card).getByText("Arabic prevails")).toBeInTheDocument();
    expect(within(card).getByText(/يحق لصاحب البيانات/)).toHaveAttribute("dir", "rtl");
    expect(within(card).getByRole("link", { name: "Open the clause" })).toHaveAttribute(
      "href",
      "/clauses/uae-pdpl%3Aart-13%3Apara-1",
    );

    const asked = await calls.find((call) => call.method === "POST")!.json();
    expect(asked).toMatchObject({
      query: "Can a user see their data?",
      include_explanatory: false,
    });
  });

  it("asks again with recitals when they are switched on", async () => {
    const { calls } = serve({
      "GET /v1/sessions/current": { body: signedIn },
      "GET /v1/documents": { body: { documents: [uae], total: 1, limit: 100, offset: 0 } },
      "POST /v1/search": { body: { laws: ["uae-pdpl"], results: [result] } },
    });
    const { router } = renderAt("/search?q=consent");
    await screen.findByText("uae-pdpl:art-13:para-1");

    await userEvent.click(screen.getByRole("switch"));

    expect(router.state.location.search).toContain("explanatory=1");
    const posts = calls.filter((call) => call.method === "POST");
    expect(await posts.at(-1)!.json()).toMatchObject({ include_explanatory: true });
  });

  it("offers the organisation's own laws to narrow to, and no other", async () => {
    serve({
      "GET /v1/sessions/current": { body: signedIn },
      "GET /v1/documents": { body: { documents: [uae], total: 1, limit: 100, offset: 0 } },
      "POST /v1/search": { body: { laws: ["uae-pdpl"], results: [result] } },
    });
    renderAt("/search?q=consent");
    await screen.findByText("uae-pdpl:art-13:para-1");

    await userEvent.click(screen.getByRole("button", { name: "All your laws" }));

    const offered = screen.getAllByRole("menuitem").map((item) => item.textContent);
    expect(offered).toEqual(["All your laws", "UAE-PDPL"]);
  });

  it("says when no law has been chosen yet, and where an administrator chooses them", async () => {
    serve({
      "GET /v1/sessions/current": { body: admin },
      "GET /v1/documents": { body: { documents: [], total: 0, limit: 100, offset: 0 } },
      "POST /v1/search": {
        status: 409,
        body: {
          type: "/problems/no-laws-selected",
          title: "No laws chosen yet",
          status: 409,
          detail: "nobody has chosen which laws apply to this organisation yet",
        },
      },
    });
    renderAt("/search?q=consent");

    expect(
      await screen.findByText(/^Nobody has chosen which laws apply yet, so there is nothing/),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Choose them in Selected laws." })).toHaveAttribute(
      "href",
      "/laws",
    );
  });

  it("tells somebody who cannot choose the laws who can", async () => {
    serve({
      "GET /v1/sessions/current": { body: signedIn },
      "GET /v1/documents": { body: { documents: [], total: 0, limit: 100, offset: 0 } },
      "POST /v1/search": {
        status: 409,
        body: {
          type: "/problems/no-laws-selected",
          title: "No laws chosen yet",
          status: 409,
          detail: "nobody has chosen which laws apply to this organisation yet",
        },
      },
    });
    renderAt("/search?q=consent");

    expect(
      await screen.findByText(/An administrator chooses them in Selected laws\.$/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Choose them in Selected laws." })).toBeNull();
  });
});
