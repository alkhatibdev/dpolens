import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { signedIn } from "@/test/fixtures";
import { acceptableUseDraft, dpo, policies, retentionDraft } from "@/test/policies";
import { renderAt } from "@/test/render";
import { problem, serve } from "@/test/server";

function rowOf(title: string): HTMLElement {
  return screen.getByText(title).closest("tr")!;
}

describe("policies", () => {
  it("lists each policy with where it stands and what comes next", async () => {
    serve({
      "GET /v1/sessions/current": { body: dpo },
      "GET /v1/policies": { body: policies },
    });
    renderAt("/policies");

    await screen.findByText("Data retention policy");
    const retention = rowOf("Data retention policy");
    expect(within(retention).getByText("since 1 Feb 2026")).toBeInTheDocument();
    expect(within(retention).getByText("3 flags to settle")).toBeInTheDocument();
    expect(within(retention).getByRole("link", { name: "Continue the review" })).toHaveAttribute(
      "href",
      "/policies/data-retention/draft",
    );
    const acceptable = rowOf("Acceptable use policy");
    expect(within(acceptable).getByText("Not published yet")).toBeInTheDocument();
    expect(within(acceptable).getByRole("link", { name: "Open the draft" })).toBeInTheDocument();
    expect(
      within(rowOf("Information security policy")).getByText("Version 3 from 1 Nov 2026"),
    ).toBeInTheDocument();
    const sample = rowOf("Sample data protection policy");
    expect(within(sample).getByText("Made up, for a new instance to search")).toBeInTheDocument();
    expect(within(sample).getByText("On the command line")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Drafts · 2" }));
    expect(screen.queryByText("Information security policy")).not.toBeInTheDocument();
    expect(screen.getByText("Acceptable use policy")).toBeInTheDocument();
  });

  it("uploads a file and opens its draft for review", async () => {
    const { calls } = serve({
      "GET /v1/sessions/current": { body: dpo },
      "GET /v1/policies": { body: policies },
      "POST /v1/policies": { status: 201, body: acceptableUseDraft },
      "GET /v1/policies/acceptable-use/draft": { body: acceptableUseDraft },
    });
    const { router } = renderAt("/policies");

    await userEvent.click(await screen.findByRole("button", { name: "Upload a policy" }));
    const dialog = screen.getByRole("dialog", { name: "Upload a policy" });
    const file = new File(["# Acceptable Use Policy"], "Acceptable Use Policy.md", {
      type: "text/markdown",
    });
    await userEvent.upload(within(dialog).getByLabelText(/Drop the file here/), file);
    expect(within(dialog).getByLabelText("Key prefix")).toHaveValue("acceptable-use-policy");
    await userEvent.clear(within(dialog).getByLabelText("Key prefix"));
    await userEvent.type(within(dialog).getByLabelText("Key prefix"), "acceptable-use");
    await userEvent.click(within(dialog).getByRole("button", { name: "Upload and read it" }));

    await screen.findByRole("heading", { name: "Acceptable use policy" });
    expect(router.state.location.pathname).toBe("/policies/acceptable-use/draft");
    const sent = calls.find((call) => call.method === "POST")!;
    const query = new URL(sent.url).searchParams;
    expect(query.get("filename")).toBe("Acceptable Use Policy.md");
    expect(query.get("slug")).toBe("acceptable-use");
    expect(sent.headers.get("Content-Type")).toBe("application/octet-stream");
    expect(await sent.text()).toBe("# Acceptable Use Policy");
  });

  it("refuses a PDF before sending it, and says what to use instead", async () => {
    const { calls } = serve({
      "GET /v1/sessions/current": { body: dpo },
      "GET /v1/policies": { body: policies },
    });
    renderAt("/policies");
    const user = userEvent.setup({ applyAccept: false });

    await user.click(await screen.findByRole("button", { name: "Upload a policy" }));
    const dialog = screen.getByRole("dialog", { name: "Upload a policy" });
    await user.upload(
      within(dialog).getByLabelText(/Drop the file here/),
      new File(["%PDF-1.7"], "retention-schedule.pdf", { type: "application/pdf" }),
    );
    await user.click(within(dialog).getByRole("button", { name: "Upload and read it" }));

    expect(within(dialog).getByRole("alert")).toHaveTextContent(
      "PDF files are not read. Use the Word or Markdown file the PDF was made from.",
    );
    expect(calls.filter((call) => call.method === "POST")).toHaveLength(0);
  });

  it("says a new version replaces the open draft, and replaces it", async () => {
    const { calls } = serve({
      "GET /v1/sessions/current": { body: dpo },
      "GET /v1/policies": { body: policies },
      "POST /v1/policies/data-retention/versions": { status: 201, body: retentionDraft },
      "GET /v1/policies/data-retention/draft": { body: retentionDraft },
    });
    renderAt("/policies");

    await userEvent.click(
      await screen.findByRole("button", { name: "More for Data retention policy" }),
    );
    await userEvent.click(screen.getByRole("menuitem", { name: "Upload a new version" }));
    const dialog = screen.getByRole("dialog", {
      name: "Upload a new version of Data retention policy",
    });
    expect(dialog).toHaveTextContent(/Version 3 is a draft already, uploaded by Mariam Al Amiri/);
    expect(dialog).toHaveTextContent("After 1 February 2026, when version 2 took effect.");
    await userEvent.upload(
      within(dialog).getByLabelText(/Drop the file here/),
      new File(["x"], "data-retention-2026-10.docx"),
    );
    await userEvent.click(within(dialog).getByRole("button", { name: "Replace the draft" }));

    await screen.findByRole("heading", { name: "Data retention policy" });
    const sent = calls.find((call) => call.method === "POST")!;
    expect(new URL(sent.url).searchParams.get("replace")).toBe("true");
  });

  it("says why an upload was refused, in the dashboard's words", async () => {
    serve({
      "GET /v1/sessions/current": { body: dpo },
      "GET /v1/policies": { body: policies },
      "POST /v1/policies": problem("policy-exists", 409),
    });
    renderAt("/policies");

    await userEvent.click(await screen.findByRole("button", { name: "Upload a policy" }));
    const dialog = screen.getByRole("dialog", { name: "Upload a policy" });
    await userEvent.upload(
      within(dialog).getByLabelText(/Drop the file here/),
      new File(["x"], "data-retention.docx"),
    );
    await userEvent.click(within(dialog).getByRole("button", { name: "Upload and read it" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "Another policy's keys start with data-retention. Choose another key prefix, or upload a new version of that policy.",
    );
  });

  it("is only for whoever uploads or publishes policies", async () => {
    serve({
      "GET /v1/sessions/current": { body: signedIn },
      "GET /v1/documents": { body: { documents: [], total: 0, limit: 100, offset: 0 } },
    });
    const { router } = renderAt("/policies");

    await screen.findAllByRole("navigation", { name: "Main" });
    expect(router.state.location.pathname).toBe("/library");
  });
});
