import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { admin, signedIn, token } from "@/test/fixtures";
import { renderAt } from "@/test/render";
import { serve } from "@/test/server";

const developer = {
  ...signedIn,
  permissions: ["documents.read", "queries.read_own", "tokens.create"],
};

describe("tokens", () => {
  it("makes a token and shows it once, with where the assistant connects", async () => {
    const made = {
      ...token({ id: "t-new", name: "Claude Code on my laptop" }),
      secret: "dpol_Xk2fQ9vR3mT8bLw1zN6cYp",
    };
    const { calls } = serve({
      "GET /v1/sessions/current": { body: developer },
      "GET /v1/tokens": { body: { tokens: [] } },
      "POST /v1/tokens": { status: 201, body: made },
      "GET /v1/instance": {
        body: { version: "0.1.0", mcp_url: "https://dpolens.example.com/mcp" },
      },
    });
    renderAt("/tokens");

    await screen.findByText("No tokens yet");
    await userEvent.click(screen.getAllByRole("button", { name: "Create a token" })[0]!);
    await userEvent.type(screen.getByLabelText("What it's for"), "Claude Code on my laptop");
    await userEvent.click(screen.getByRole("button", { name: "Create the token" }));

    const shown = await screen.findByRole("dialog", { name: "Your new token" });
    expect(within(shown).getByText("dpol_Xk2fQ9vR3mT8bLw1zN6cYp")).toBeInTheDocument();
    expect(await within(shown).findByText("https://dpolens.example.com/mcp")).toBeInTheDocument();
    const body = await calls.find((call) => call.method === "POST")!.json();
    expect(body.permissions).toEqual(["documents.read"]);
    expect(body.expires_at).not.toBeNull();

    await userEvent.click(within(shown).getByRole("button", { name: "Done" }));
    expect(screen.queryByText("dpol_Xk2fQ9vR3mT8bLw1zN6cYp")).not.toBeInTheDocument();
  });

  it("strikes out what a token no longer may do, and warns before revoking the MCP server's", async () => {
    serve({
      "GET /v1/sessions/current": { body: admin },
      "GET /v1/tokens": ({ url }) => ({
        body: {
          tokens:
            new URL(url).searchParams.get("everyone") === "true"
              ? [
                  token({
                    id: "t-1",
                    name: "admin-scripts",
                    owner: { id: "p-rami", display_name: "Rami Aziz", kind: "person" },
                    permissions: ["documents.read", "users.manage"],
                    effective_permissions: ["documents.read"],
                  }),
                  token({
                    id: "t-2",
                    name: "mcp",
                    owner: { id: "p-mcp", display_name: "MCP server", kind: "service_account" },
                    trusted_surface: true,
                  }),
                ]
              : [],
        },
      }),
    });
    renderAt("/tokens");

    await userEvent.click(await screen.findByRole("button", { name: /^Everyone's/ }));
    expect(
      await screen.findByText(
        "Rami Aziz no longer holds Manage people, so this token doesn't either.",
      ),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Revoke mcp" }));
    expect(
      await screen.findByRole("dialog", { name: "Revoke the MCP server's token?" }),
    ).toBeInTheDocument();
  });
});
