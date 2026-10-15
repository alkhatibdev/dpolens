import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { admin, lawsChosen, lawsUnchosen, overview, uae } from "@/test/fixtures";
import { renderAt } from "@/test/render";
import { serve } from "@/test/server";

describe("the first run", () => {
  it("asks which laws apply, and saves the answer before going on", async () => {
    const { calls } = serve({
      "GET /v1/sessions/current": { body: admin },
      "GET /v1/laws": { body: lawsUnchosen },
      "PUT /v1/laws/selection": { body: lawsChosen },
      "GET /v1/overview": { body: overview },
    });
    const { router } = renderAt("/setup");

    expect(
      await screen.findByRole("heading", { name: "Which laws apply to your organisation?" }),
    ).toBeInTheDocument();
    const save = screen.getByRole("button", { name: "Save and continue" });
    expect(save).toBeDisabled();
    await userEvent.click(screen.getByRole("checkbox", { name: uae.title }));
    await userEvent.click(save);

    await waitFor(() => expect(router.state.location.pathname).toBe("/overview"));
    const put = calls.find((call) => call.method === "PUT")!;
    expect(await put.json()).toEqual({ laws: ["uae-pdpl"] });
  });

  it("goes on without choosing when it is decided later", async () => {
    const { calls } = serve({
      "GET /v1/sessions/current": { body: admin },
      "GET /v1/laws": { body: lawsUnchosen },
      "GET /v1/overview": { body: overview },
    });
    const { router } = renderAt("/setup");

    await userEvent.click(await screen.findByRole("button", { name: "Decide later" }));

    await waitFor(() => expect(router.state.location.pathname).toBe("/overview"));
    expect(calls.some((call) => call.method === "PUT")).toBe(false);
  });

  it("is not asked again once somebody has chosen", async () => {
    serve({
      "GET /v1/sessions/current": { body: admin },
      "GET /v1/laws": { body: lawsChosen },
      "GET /v1/overview": { body: overview },
    });
    const { router } = renderAt("/setup");

    await waitFor(() => expect(router.state.location.pathname).toBe("/overview"));
    expect(screen.queryByText("Which laws apply to your organisation?")).not.toBeInTheDocument();
  });
});
