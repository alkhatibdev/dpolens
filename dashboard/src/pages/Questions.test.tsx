import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { admin, dpo, privacyLead, question } from "@/test/fixtures";
import { renderAt } from "@/test/render";
import { serve } from "@/test/server";

const webhook = question({
  id: "q-1",
  question: "can I log [redacted:email] when a payment webhook fails",
  redaction_count: 1,
  redaction_types: ["email"],
});
const cctv = question({
  id: "q-2",
  question: "retention period for CCTV footage",
  status: "no_match",
  results: [],
});

function page(questions: unknown[], identities = false) {
  return { body: { questions, total: questions.length, next: null, identities } };
}

describe("the questions log", () => {
  it("shows questions as stored, with what was taken out and no names", async () => {
    serve({
      "GET /v1/sessions/current": { body: dpo },
      "GET /v1/queries": page([webhook, cctv]),
      "GET /v1/documents": { body: { documents: [], total: 0, limit: 100, offset: 0 } },
    });
    renderAt("/logs");

    const row = (await screen.findByText(/can I log/)).closest("tr")!;
    expect(within(row).getByText("email removed")).toBeInTheDocument();
    expect(within(row).getByText("Hidden")).toBeInTheDocument();
    expect(row).toHaveTextContent("GDPR · Article 17(1)");
    // The numbering keeps its own direction, which an Arabic label needs.
    expect(within(row).getByText("Article 17(1)").tagName).toBe("BDI");
    expect(screen.queryByRole("button", { name: "Show who asked" })).not.toBeInTheDocument();

    await userEvent.click(within(row).getByRole("button", { name: "Show what it returned" }));
    expect(screen.getByText("What it returned")).toBeInTheDocument();
    expect(screen.getByText("1 × email")).toBeInTheDocument();
    // Questions are kept unless the instance is set to delete them.
    expect(screen.getByText("Not scheduled")).toBeInTheDocument();
  });

  it("says when a question goes, where a retention is set", async () => {
    serve({
      "GET /v1/sessions/current": { body: dpo },
      "GET /v1/queries": page([{ ...webhook, expires_at: "2026-11-18T09:00:00Z" }]),
      "GET /v1/documents": { body: { documents: [], total: 0, limit: 100, offset: 0 } },
    });
    renderAt("/logs");

    const row = (await screen.findByText(/can I log/)).closest("tr")!;
    await userEvent.click(within(row).getByRole("button", { name: "Show what it returned" }));
    expect(screen.getByText("18 November 2026")).toBeInTheDocument();
  });

  it("offers no names to the seeded admin, who starts without them", async () => {
    serve({
      "GET /v1/sessions/current": { body: admin },
      "GET /v1/queries": page([webhook]),
      "GET /v1/documents": { body: { documents: [], total: 0, limit: 100, offset: 0 } },
    });
    renderAt("/logs");

    await screen.findByText(/can I log/);
    expect(screen.getByText("Names are hidden")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Show who asked" })).not.toBeInTheDocument();
  });

  it("asks before showing names, then asks the API for them", async () => {
    const { calls } = serve({
      "GET /v1/sessions/current": { body: privacyLead },
      "GET /v1/queries": ({ url }) =>
        new URL(url).searchParams.get("identities") === "true"
          ? page(
              [
                {
                  ...webhook,
                  asker: {
                    id: "p-sara",
                    display_name: "Sara Nasser",
                    email: "sara@example.com",
                    kind: "person",
                  },
                },
              ],
              true,
            )
          : page([webhook]),
      "GET /v1/documents": { body: { documents: [], total: 0, limit: 100, offset: 0 } },
    });
    renderAt("/logs");

    await userEvent.click(await screen.findByRole("button", { name: "Show who asked" }));
    expect(screen.getByText(/records that you looked/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show names" }));

    expect(await screen.findByText("Sara Nasser")).toBeInTheDocument();
    expect(screen.getByText("Names are shown")).toBeInTheDocument();
    expect(calls.some((call) => new URL(call.url).searchParams.get("identities") === "true")).toBe(
      true,
    );
  });

  it("opens on the questions that found nothing when the Overview links there", async () => {
    const { calls } = serve({
      "GET /v1/sessions/current": { body: dpo },
      "GET /v1/queries": page([cctv]),
      "GET /v1/documents": { body: { documents: [], total: 0, limit: 100, offset: 0 } },
    });
    renderAt("/logs?status=no_match");

    await screen.findByText("retention period for CCTV footage");
    const asked = calls.filter((call) => call.url.includes("/v1/queries"));
    expect(new URL(asked[0]!.url).searchParams.getAll("status")).toEqual(["no_match"]);
  });
});
