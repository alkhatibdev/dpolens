import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { admin, signedIn, uae } from "@/test/fixtures";
import { renderAt } from "@/test/render";
import { problem, serve } from "@/test/server";

describe("the shell", () => {
  it("shows only the avatar, and the name, role and sign-out in its menu", async () => {
    let signedOut = false;
    const { calls } = serve({
      "GET /v1/sessions/current": () =>
        signedOut ? problem("session-ended", 401, { reason: "unknown" }) : { body: signedIn },
      "GET /v1/documents": { body: { documents: [uae], total: 1, limit: 100, offset: 0 } },
      "DELETE /v1/sessions/current": () => {
        signedOut = true;
        return { status: 204 };
      },
    });
    const { router } = renderAt("/library");

    const avatar = await screen.findByRole("button", { name: "Your account" });
    expect(avatar).toHaveTextContent("MA");
    expect(screen.queryByText("Mariam Al Amiri")).not.toBeInTheDocument();

    await userEvent.click(avatar);
    expect(await screen.findByText("Mariam Al Amiri")).toBeInTheDocument();
    expect(screen.getByText("DPO")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("menuitem", { name: "Sign out" }));

    await screen.findByRole("heading", { name: "Sign in" });
    expect(calls.some((call) => call.method === "DELETE")).toBe(true);
    expect(router.state.location.pathname).toBe("/sign-in");
  });

  it("asks the library from the top bar", async () => {
    serve({
      "GET /v1/sessions/current": { body: signedIn },
      "GET /v1/documents": { body: { documents: [uae], total: 1, limit: 100, offset: 0 } },
      "POST /v1/search": { body: { laws: ["uae-pdpl"], results: [] } },
    });
    const { router } = renderAt("/library");

    const box = (await screen.findAllByRole("searchbox"))[0]!;
    await userEvent.type(box, "Can a user see their data?{Enter}");

    expect(router.state.location.pathname).toBe("/search");
    expect(router.state.location.search).toBe("?q=Can%20a%20user%20see%20their%20data%3F");
  });

  it("shows each section only to whoever it is for", async () => {
    serve({
      "GET /v1/sessions/current": { body: signedIn },
      "GET /v1/documents": { body: { documents: [uae], total: 1, limit: 100, offset: 0 } },
    });
    renderAt("/library");

    const main = (await screen.findAllByRole("navigation", { name: "Main" }))[0]!;
    expect(main).toHaveTextContent("Library");
    expect(main).toHaveTextContent("Tokens");
    expect(main).not.toHaveTextContent("Users and roles");
  });

  it("changes the password from the account menu", async () => {
    const { calls } = serve({
      "GET /v1/sessions/current": { body: admin },
      "GET /v1/documents": { body: { documents: [uae], total: 1, limit: 100, offset: 0 } },
      "PUT /v1/sessions/current/password": { status: 204 },
    });
    renderAt("/library");

    await userEvent.click(await screen.findByRole("button", { name: "Your account" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Change your password" }));
    await userEvent.type(screen.getByLabelText("Current password"), "correct horse battery");
    await userEvent.type(screen.getByLabelText("New password"), "a kettle on the third shelf");
    await userEvent.click(screen.getByRole("button", { name: "Change the password" }));

    expect(
      await screen.findByRole("dialog", { name: "Your password is changed" }),
    ).toBeInTheDocument();
    const sent = calls.find((call) => call.method === "PUT")!;
    expect(await sent.json()).toEqual({
      current: "correct horse battery",
      new: "a kettle on the third shelf",
    });
  });
});
