import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { library } from "@/test/library";
import { signedIn } from "@/test/fixtures";
import { renderAt } from "@/test/render";
import { problem, serve } from "@/test/server";

afterEach(() => {
  globalThis.history.replaceState(null, "", "/");
});

describe("choosing a password from a link", () => {
  it("greets the person, sets the password and signs them in", async () => {
    globalThis.history.replaceState(null, "", "/welcome#k7Qe2LmV9xTz");
    const { calls } = serve({
      "POST /v1/sign-in-links/lookup": {
        body: {
          email: "lina@example.com",
          display_name: "Lina Farouk",
          expires_at: "2026-10-18T05:05:00Z",
        },
      },
      "POST /v1/sessions/from-link": { status: 201, body: signedIn },
      "GET /v1/sessions/current": { body: signedIn },
      ...library,
    });
    const { router } = renderAt("/welcome");

    expect(await screen.findByRole("heading", { name: "Welcome, Lina" })).toBeInTheDocument();
    expect(globalThis.location.hash).toBe("");
    await userEvent.type(screen.getByLabelText("New password"), "olive harbour lantern");
    await userEvent.click(screen.getByRole("button", { name: "Save and sign in" }));

    await screen.findByRole("heading", { name: "Library" });
    expect(router.state.location.pathname).toBe("/library");
    const spent = calls.find((call) => call.url.endsWith("/v1/sessions/from-link"))!;
    expect(await spent.json()).toEqual({
      secret: "k7Qe2LmV9xTz",
      password: "olive harbour lantern",
    });
  });

  it("says a used or expired link no longer works", async () => {
    globalThis.history.replaceState(null, "", "/welcome#spent");
    serve({ "POST /v1/sign-in-links/lookup": problem("sign-in-link-unusable", 410) });
    renderAt("/welcome");

    expect(
      await screen.findByRole("heading", { name: "This link no longer works" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Ask your administrator for a new one\./)).toBeInTheDocument();
  });
});
