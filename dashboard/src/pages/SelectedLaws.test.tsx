import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { admin, gdprLaw, lawsChosen, lawsUnchosen, signedIn, uae, uaeLaw } from "@/test/fixtures";
import { renderAt } from "@/test/render";
import { serve } from "@/test/server";

const GDPR = "General Data Protection Regulation";

describe("selected laws", () => {
  it("says what searches cover, and who chose it and when", async () => {
    serve({
      "GET /v1/sessions/current": { body: admin },
      "GET /v1/laws": { body: lawsChosen },
    });
    renderAt("/laws");

    expect(
      await screen.findByRole("heading", { name: "Searches cover UAE PDPL, and your policies" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/^Chosen by Yousef Haddad on 14 Oct at \d\d:\d\d\./),
    ).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: uae.title })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: GDPR })).not.toBeChecked();
    expect(screen.getByText("173")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Read it in the library" })[0]).toHaveAttribute(
      "href",
      "/library/gdpr",
    );
  });

  it("saves a changed selection, and shows it at once", async () => {
    const { calls } = serve({
      "GET /v1/sessions/current": { body: admin },
      "GET /v1/laws": { body: lawsChosen },
      "PUT /v1/laws/selection": {
        body: {
          laws: [gdprLaw, uaeLaw],
          selected: ["gdpr", "uae-pdpl"],
          changed: { ...lawsChosen.changed!, at: new Date().toISOString() },
        },
      },
    });
    renderAt("/laws");

    await userEvent.click(await screen.findByRole("checkbox", { name: GDPR }));
    expect(screen.getByText("Adds GDPR. It applies to the next search.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Save the selection" }));

    expect(
      await screen.findByRole("heading", {
        name: "Searches cover GDPR and UAE PDPL, and your policies",
      }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save the selection" })).not.toBeInTheDocument();
    const put = calls.find((call) => call.method === "PUT")!;
    expect(await put.json()).toEqual({ laws: ["gdpr", "uae-pdpl"] });
  });

  it("will not save an empty selection, and says what to do instead", async () => {
    serve({
      "GET /v1/sessions/current": { body: admin },
      "GET /v1/laws": { body: lawsChosen },
    });
    renderAt("/laws");

    await userEvent.click(await screen.findByRole("checkbox", { name: uae.title }));

    expect(screen.getByText("Removes UAE PDPL. Choose at least one law.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save the selection" })).toBeDisabled();
  });

  it("offers no way back to searching every law", async () => {
    serve({
      "GET /v1/sessions/current": { body: admin },
      "GET /v1/laws": { body: lawsChosen },
    });
    renderAt("/laws");

    await screen.findByRole("heading", { name: "Searches cover UAE PDPL, and your policies" });

    expect(screen.queryByText("Search every law instead")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Go back to every law" })).not.toBeInTheDocument();
  });

  it("says nothing is searched on a new instance, where nobody has chosen yet", async () => {
    serve({
      "GET /v1/sessions/current": { body: admin },
      "GET /v1/laws": { body: lawsUnchosen },
    });
    renderAt("/laws");

    expect(
      await screen.findByRole("heading", { name: "Nothing is searched until someone chooses" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: GDPR })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: uae.title })).not.toBeChecked();
  });

  it("marks a law that arrived after the laws were chosen", async () => {
    serve({
      "GET /v1/sessions/current": { body: admin },
      "GET /v1/laws": {
        body: { ...lawsChosen, laws: [{ ...gdprLaw, searched: false, new: true }, uaeLaw] },
      },
    });
    renderAt("/laws");

    const card = (await screen.findByRole("checkbox", { name: GDPR })).closest("label")!;
    expect(within(card).getByText("New")).toBeInTheDocument();
    const other = screen.getByRole("checkbox", { name: uae.title }).closest("label")!;
    expect(within(other).queryByText("New")).not.toBeInTheDocument();
  });

  it("is not offered to somebody who may not change settings", async () => {
    serve({
      "GET /v1/sessions/current": { body: signedIn },
      "GET /v1/documents": { body: { documents: [uae], total: 1, limit: 100, offset: 0 } },
    });
    renderAt("/laws");

    expect(await screen.findByRole("heading", { name: "Library" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Selected laws" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Settings" })).not.toBeInTheDocument();
  });
});
