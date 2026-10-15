import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { admin, settings, signedIn } from "@/test/fixtures";
import { renderAt } from "@/test/render";
import { serve } from "@/test/server";

const intact = {
  ok: true,
  entries: 1204,
  first_broken_seq: null,
  reason: null,
  out_of_order: [],
  anchored_to_genesis: true,
  checked_at: "2026-10-15T10:00:00Z",
};

describe("settings", () => {
  it("shows how the instance is set up, and where to read how to change it", async () => {
    serve({
      "GET /v1/sessions/current": { body: admin },
      "GET /v1/settings": { body: settings },
      "GET /v1/governance/verification": { body: intact },
    });
    renderAt("/settings");

    expect(await screen.findByText("365 days")).toBeInTheDocument();
    expect(screen.getByText("Emirates ID numbers")).toBeInTheDocument();
    expect(screen.getByText("30 minutes without activity")).toBeInTheDocument();
    expect(screen.getByText("5 in 15 minutes")).toBeInTheDocument();
    expect(screen.getByText("https://dpolens.example.com/mcp")).toBeInTheDocument();
    expect(screen.getByText("60 a minute")).toBeInTheDocument();
    expect(
      screen.getByText("Nothing a person asks or reads here is sent to another service."),
    ).toBeInTheDocument();
    expect(screen.getByText("2 September 2026")).toBeInTheDocument();
    expect(await screen.findByText(/1,204 entries, intact/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /How to change them/ })).toHaveAttribute(
      "href",
      "https://github.com/alkhatibdev/dpolens/blob/main/docs/configuration.md",
    );
  });

  it("leaves out the governance log for somebody who may not read it", async () => {
    const { calls } = serve({
      "GET /v1/sessions/current": {
        body: { ...signedIn, permissions: ["documents.read", "settings.manage"] },
      },
      "GET /v1/settings": { body: settings },
    });
    renderAt("/settings");

    await screen.findByText("365 days");
    expect(screen.queryByText("Governance log")).not.toBeInTheDocument();
    await waitFor(() =>
      expect(calls.some((call) => call.url.includes("/v1/governance/"))).toBe(false),
    );
  });
});
