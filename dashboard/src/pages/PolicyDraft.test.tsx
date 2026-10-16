import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { PolicyDraft } from "@/api/policies";
import {
  acceptableUseDraft,
  acceptableUseFile,
  dpo,
  policies,
  retentionDraft,
} from "@/test/policies";
import { renderAt } from "@/test/render";
import { problem, serve } from "@/test/server";

const ACCEPTED_AT = "2026-10-16T09:53:00Z";

function settled(draft: PolicyDraft, position: number): PolicyDraft {
  return {
    ...draft,
    revision: draft.revision + 1,
    flags: draft.flags.map((flag) =>
      flag.position === position
        ? { ...flag, accepted_by: "Mariam Al Amiri", accepted_at: ACCEPTED_AT }
        : flag,
    ),
  };
}

function everyFlagSettled(draft: PolicyDraft): PolicyDraft {
  return draft.flags.reduce((found, flag) => settled(found, flag.position), draft);
}

const reviewing = {
  "GET /v1/sessions/current": { body: dpo },
  "GET /v1/policies": { body: policies },
  "GET /v1/policies/acceptable-use/versions/1/file": { body: acceptableUseFile },
};

describe("a draft under review", () => {
  it("accepts a flag against the revision it read", async () => {
    const { calls } = serve({
      ...reviewing,
      "GET /v1/policies/acceptable-use/draft": { body: acceptableUseDraft },
      "POST /v1/policies/acceptable-use/draft/flags/accept": {
        body: settled(acceptableUseDraft, 2),
      },
    });
    renderAt("/policies/acceptable-use/draft");

    expect(await screen.findByText("2 flags to settle first")).toBeInTheDocument();
    const numbering = screen.getByText("3.4 follows 3.2.").closest("div.flex-col")! as HTMLElement;
    await userEvent.click(within(numbering).getByRole("button", { name: "Accept as read" }));

    expect(await screen.findByText(/Accepted as read by Mariam Al Amiri/)).toBeInTheDocument();
    expect(screen.getByText("1 flag to settle first")).toBeInTheDocument();
    const sent = calls.find((call) => call.method === "POST")!;
    expect(sent.headers.get("If-Match")).toBe('"1"');
    expect(await sent.json()).toEqual({ positions: [2] });
  });

  it("says who changed the draft when a change comes after theirs, and reloads it", async () => {
    let read = 0;
    serve({
      ...reviewing,
      "GET /v1/policies/acceptable-use/draft": () => {
        read += 1;
        return { body: read === 1 ? acceptableUseDraft : settled(acceptableUseDraft, 2) };
      },
      "POST /v1/policies/acceptable-use/draft/flags/accept": problem("edit-conflict", 412, {
        revision: 2,
        updated_by: "Yousef Haddad",
        updated_at: new Date().toISOString(),
      }),
    });
    renderAt("/policies/acceptable-use/draft");

    const numbering = (await screen.findByText("3.4 follows 3.2.")).closest(
      "div.flex-col",
    )! as HTMLElement;
    await userEvent.click(within(numbering).getByRole("button", { name: "Accept as read" }));

    const conflict = await screen.findByRole("dialog", {
      name: "Yousef Haddad changed this draft",
    });
    expect(conflict).toHaveTextContent(/That was today at \d\d:\d\d, after you opened it/);
    await userEvent.click(within(conflict).getByRole("button", { name: "Reload the draft" }));
    expect(await screen.findByText("1 flag to settle first")).toBeInTheDocument();
  });

  it("shows the file as read beside its clauses, and lights the clause chosen", async () => {
    serve({
      ...reviewing,
      "GET /v1/policies/acceptable-use/draft": { body: acceptableUseDraft },
    });
    renderAt("/policies/acceptable-use/draft");

    expect(await screen.findByText("Set aside · contents")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /^personal-use\s*Personal use:/ }));

    expect(
      screen.getByText("Personal use:", { selector: "p" }).closest("[data-lit]"),
    ).not.toBeNull();
    expect(
      screen.getByText(/^Read as a heading from its type: bold, larger or in capitals/),
    ).toHaveTextContent("It holds the clause under it.");
    expect(
      screen.getByText("3.2 Lock your screen whenever you leave your desk.").closest("[data-lit]"),
    ).toBeNull();
  });

  it("shows what changed against the version before, and asks once before calling a match wrong", async () => {
    const { calls } = serve({
      ...reviewing,
      "GET /v1/policies/data-retention/draft": { body: retentionDraft },
      "POST /v1/policies/data-retention/draft/matches/data-retention%3A4.3/reject": {
        body: retentionDraft,
      },
      [`GET /v1/clauses/${encodeURIComponent("data-retention:4.2")}/activity`]: {
        body: { key: "data-retention:4.2", total: 64, by_day: [] },
      },
    });
    renderAt("/policies/data-retention/draft");

    expect(
      await screen.findByRole("heading", {
        name: "Against version 2, in force since 1 February 2026",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("Renumbered, was 4.2")).toBeInTheDocument();
    expect(screen.getByText("Renumbered and reworded, was 4.3")).toBeInTheDocument();
    expect(screen.getByText("after the end of the financial year", { selector: "ins" }));
    expect(
      await screen.findByText(/^Cited 64 times in the last 7 days, as version 2's 4.2/),
    ).toBeInTheDocument();

    const moved = screen
      .getByText(/^4.3 continues 4.2 from version 2/)
      .closest("div.flex-col")! as HTMLElement;
    await userEvent.click(within(moved).getByRole("button", { name: "It's a different rule" }));
    const asked = screen.getByRole("dialog", { name: "Is 4.3 a different rule?" });
    expect(asked).toHaveTextContent(
      "4.3 becomes new, and version 2's 4.2 is removed: a citation of it will say its rule was removed",
    );
    await userEvent.click(within(asked).getByRole("button", { name: "It's a different rule" }));

    const sent = calls.find((call) => call.method === "POST")!;
    expect(sent.headers.get("If-Match")).toBe('"3"');
  });

  it("publishes once every flag is settled, and says so on Policies", async () => {
    const ready = everyFlagSettled(retentionDraft);
    serve({
      ...reviewing,
      "GET /v1/policies/data-retention/draft": { body: ready },
      "POST /v1/policies/data-retention/draft/publish": {
        body: {
          ...ready.version,
          label: "3",
          status: "published",
          published_at: ACCEPTED_AT,
          published_by: "Mariam Al Amiri",
          indexing: "todo",
        },
      },
    });
    const { router } = renderAt("/policies/data-retention/draft");

    await userEvent.click(await screen.findByRole("button", { name: "Publish" }));
    const confirm = screen.getByRole("dialog", {
      name: "Publish version 3 of Data retention policy?",
    });
    expect(confirm).toHaveTextContent("3, all settled");
    expect(confirm).toHaveTextContent("Until then, version 2 stays in force.");
    await userEvent.click(within(confirm).getByRole("button", { name: "Publish version 3" }));

    expect(
      await screen.findByText("Version 3 of Data retention policy is published"),
    ).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/policies");
  });
});
