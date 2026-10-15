import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { admin, people, person, roles, signedIn } from "@/test/fixtures";
import { renderAt } from "@/test/render";
import { problem, serve } from "@/test/server";

const lists = {
  "GET /v1/sessions/current": { body: admin },
  "GET /v1/users": { body: { people } },
  "GET /v1/roles": { body: { roles } },
};

describe("people", () => {
  it("lists everyone with what the page needs to say about them", async () => {
    serve(lists);
    renderAt("/users");

    const table = await screen.findByRole("table");
    const lina = within(table).getByText("Lina Farouk").closest("tr")!;
    expect(within(lina).getByText("Has not chosen a password")).toBeInTheDocument();
    expect(within(lina).getByText(/Link works until/)).toBeInTheDocument();
    const ahmed = within(table).getByText("Ahmed Saleh").closest("tr")!;
    expect(within(ahmed).getByText(/Deactivated on 2 Oct 2026/)).toBeInTheDocument();
    const mcp = within(table).getByText("MCP server").closest("tr")!;
    expect(within(mcp).getByText("Acts for each developer")).toBeInTheDocument();
    expect(within(mcp).queryByRole("button")).not.toBeInTheDocument();
    expect(within(table).getByText("(you)")).toBeInTheDocument();
  });

  it("adds a person, then hands over the link that lets them choose a password", async () => {
    const lina = person({ id: "p-new", display_name: "Lina Farouk", has_password: false });
    const { calls } = serve({
      ...lists,
      "POST /v1/users": { status: 201, body: lina },
      "POST /v1/users/p-new/sign-in-links": {
        status: 201,
        body: { secret: "k7Qe2LmV9xTz", expires_at: "2026-10-18T05:05:00Z" },
      },
    });
    renderAt("/users");

    await userEvent.click(await screen.findByRole("button", { name: "Add a person" }));
    await userEvent.type(screen.getByLabelText("Name"), "Lina Farouk");
    await userEvent.type(screen.getByLabelText("Email"), "lina@example.com");
    await userEvent.click(screen.getByRole("checkbox", { name: /Developer/ }));
    await userEvent.click(screen.getByRole("button", { name: "Add Lina Farouk" }));

    expect(
      await screen.findByRole("dialog", { name: "Send Lina Farouk this link" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(`${globalThis.location.origin}/welcome#k7Qe2LmV9xTz`),
    ).toBeInTheDocument();
    const added = calls.find((call) => call.method === "POST" && call.url.endsWith("/v1/users"));
    expect(await added!.json()).toEqual({
      email: "lina@example.com",
      display_name: "Lina Farouk",
      roles: ["Developer"],
    });
  });

  it("says plainly when the last person who can manage roles would be deactivated", async () => {
    serve({
      ...lists,
      "GET /v1/users": {
        body: { people: [...people, person({ id: "p-sara", display_name: "Sara Nasser" })] },
      },
      "PATCH /v1/users/p-sara": problem("lockout-refused", 409),
    });
    renderAt("/users");

    await userEvent.click(await screen.findByRole("button", { name: "Actions for Sara Nasser" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Deactivate" }));
    await userEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "Deactivate" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Sara Nasser is the last active person who can manage roles.",
    );
  });

  it("sends someone who may not manage people to the roles they may read", async () => {
    serve({
      "GET /v1/sessions/current": {
        body: { ...signedIn, permissions: ["documents.read", "roles.manage"] },
      },
      "GET /v1/roles": { body: { roles } },
      "GET /v1/permissions": { body: { permissions: [] } },
    });
    const { router } = renderAt("/users");

    await screen.findByRole("link", { name: /^DPO/ });
    expect(router.state.location.pathname).toBe("/users/roles");
    expect(screen.queryByRole("link", { name: /^People/ })).not.toBeInTheDocument();
  });
});
