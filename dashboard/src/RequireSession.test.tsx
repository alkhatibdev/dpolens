import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderAt } from "@/test/render";
import { problem, serve } from "@/test/server";

describe("a page behind sign-in", () => {
  it("sends anyone not signed in to sign in", async () => {
    serve({ "GET /v1/sessions/current": problem("unauthenticated", 401) });
    const { router } = renderAt("/library");

    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/sign-in");
  });

  it("says when the session ran out", async () => {
    serve({
      "GET /v1/sessions/current": problem("session-ended", 401, { reason: "expired" }),
    });
    renderAt("/library");

    expect(await screen.findByText(/reached its time limit/)).toBeInTheDocument();
  });
});
