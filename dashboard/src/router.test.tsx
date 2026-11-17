import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { signedIn } from "@/test/fixtures";
import { renderAt } from "@/test/render";
import { problem, serve } from "@/test/server";

// As if these pages' files had gone with an upgrade, or the network had dropped.
vi.mock("@/pages/Search", () => {
  throw new TypeError("Failed to fetch dynamically imported module");
});
vi.mock("@/pages/SignIn", () => {
  throw new TypeError("Failed to fetch dynamically imported module");
});

describe("a page whose file cannot be fetched", () => {
  it("says so inside the frame, and offers to load it again", async () => {
    serve({ "GET /v1/sessions/current": { body: signedIn } });
    renderAt("/search?q=retention");

    expect(await screen.findByRole("alert")).toHaveTextContent("This didn't load.");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    expect(screen.getAllByRole("navigation", { name: "Main" }).length).toBeGreaterThan(0);
  });

  it("says so on a page outside the frame", async () => {
    serve({ "GET /v1/sessions/current": problem("unauthenticated", 401) });
    renderAt("/sign-in");

    expect(await screen.findByRole("alert")).toHaveTextContent("This didn't load.");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});
