import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { gdpr, signedIn, uae } from "@/test/fixtures";
import { renderAt } from "@/test/render";
import { serve } from "@/test/server";

beforeEach(() => {
  serve({
    "GET /v1/sessions/current": { body: signedIn },
    "GET /v1/documents": { body: { documents: [gdpr, uae], total: 2, limit: 100, offset: 0 } },
  });
});

describe("the library", () => {
  it("shows each document with what a reader needs to choose it", async () => {
    renderAt("/library");

    const card = (await screen.findByText(uae.title)).closest("a")!;
    expect(within(card).getByText("Law")).toBeInTheDocument();
    expect(within(card).getByText("United Arab Emirates")).toBeInTheDocument();
    expect(within(card).getByText(/العربية · prevails/)).toHaveAttribute("lang", "ar");
    expect(within(card).getByText("199")).toBeInTheDocument();
    expect(within(card).getByText("2 Jan 2022")).toBeInTheDocument();
    expect(card).toHaveAttribute("href", "/library/uae-pdpl");

    // Every law the library lists is one the organisation chose, so none says so.
    expect(screen.queryByText("Not in your selected laws")).not.toBeInTheDocument();
  });

  it("says where the organisation's policies will appear", async () => {
    renderAt("/library");

    expect(await screen.findByText("Your organisation's policies")).toBeInTheDocument();
  });

  it("filters by language", async () => {
    renderAt("/library");
    await screen.findByText(uae.title);

    await userEvent.click(screen.getByRole("button", { name: "العربية" }));

    expect(screen.getByText(uae.title)).toBeInTheDocument();
    expect(screen.queryByText(gdpr.title)).not.toBeInTheDocument();
  });
});
