import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { renderAt } from "@/test/render";
import { problem, serve } from "@/test/server";
import { dpo, lawsChosen, lawsUnchosen, overview, signedIn, uae } from "@/test/fixtures";

async function fillAndSubmit() {
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText("Email"), "mariam@example.com");
  await user.type(screen.getByLabelText("Password"), "correct horse battery staple");
  await user.click(screen.getByRole("button", { name: "Sign in" }));
}

describe("signing in", () => {
  it("says the same thing for any wrong email or password", async () => {
    serve({
      "GET /v1/sessions/current": problem("unauthenticated", 401),
      "POST /v1/sessions": problem("sign-in-refused", 401),
    });
    renderAt("/sign-in");

    await fillAndSubmit();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "That email and password don't match.",
    );
  });

  it("says how long to wait after too many attempts", async () => {
    serve({
      "GET /v1/sessions/current": problem("unauthenticated", 401),
      "POST /v1/sessions": {
        ...problem("too-many-attempts", 429),
        headers: { "Retry-After": "600" },
      },
    });
    renderAt("/sign-in");

    await fillAndSubmit();

    expect(await screen.findByRole("alert")).toHaveTextContent("Try again in 10 minutes.");
  });

  it("opens the library once the password matches", async () => {
    let signed = false;
    serve({
      "GET /v1/sessions/current": () =>
        signed ? { body: signedIn } : problem("unauthenticated", 401),
      "POST /v1/sessions": () => {
        signed = true;
        return { status: 201, body: signedIn };
      },
      "GET /v1/documents": { body: { documents: [uae], total: 1, limit: 100, offset: 0 } },
    });
    renderAt("/sign-in");

    await fillAndSubmit();

    expect(await screen.findByRole("heading", { name: "Library" })).toBeInTheDocument();
  });

  it("opens the overview for somebody who may read every question", async () => {
    let signed = false;
    serve({
      "GET /v1/sessions/current": () => (signed ? { body: dpo } : problem("unauthenticated", 401)),
      "POST /v1/sessions": () => {
        signed = true;
        return { status: 201, body: dpo };
      },
      "GET /v1/laws": { body: lawsChosen },
      "GET /v1/overview": { body: overview },
    });
    const { router } = renderAt("/sign-in");

    await fillAndSubmit();

    expect(await screen.findByRole("heading", { name: "Overview" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/overview");
  });

  it("asks which laws apply when somebody who may choose signs in and nobody has", async () => {
    let signed = false;
    serve({
      "GET /v1/sessions/current": () => (signed ? { body: dpo } : problem("unauthenticated", 401)),
      "POST /v1/sessions": () => {
        signed = true;
        return { status: 201, body: dpo };
      },
      "GET /v1/laws": { body: lawsUnchosen },
    });
    const { router } = renderAt("/sign-in");

    await fillAndSubmit();

    expect(
      await screen.findByRole("heading", { name: "Which laws apply to your organisation?" }),
    ).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/setup");
  });

  it("says why a session ended", async () => {
    serve({ "GET /v1/sessions/current": problem("unauthenticated", 401) });
    renderAt("/sign-in?reason=idle");

    expect(await screen.findByRole("status")).toHaveTextContent(
      "You were signed out after a while without activity.",
    );
  });

  it("never names a command or an administrator", async () => {
    serve({ "GET /v1/sessions/current": problem("unauthenticated", 401) });
    renderAt("/sign-in");

    await screen.findByLabelText("Email");
    expect(document.body.textContent).not.toMatch(/dpolens |administrator/i);
  });
});
