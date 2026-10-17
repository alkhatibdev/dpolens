import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { PolicyDraft } from "@/api/policies";
import {
  acceptableUseDraft,
  acceptableUseFile,
  askingDraft,
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

  it("asks whether a new clause is a rule nothing continues, and says it is", async () => {
    const paired: PolicyDraft = {
      ...retentionDraft,
      revision: 4,
      flags: [
        ...retentionDraft.flags.slice(0, 2),
        {
          ...askingDraft.flags[2]!,
          resolved_by: "Mariam Al Amiri",
          resolved_at: ACCEPTED_AT,
          resolution: "match-made",
          resolution_key: "data-retention:4.3",
        },
      ],
    };
    const { calls } = serve({
      ...reviewing,
      "GET /v1/policies/data-retention/draft": { body: askingDraft },
      "POST /v1/policies/data-retention/draft/matches/data-retention%3A4.4": { body: paired },
    });
    renderAt("/policies/data-retention/draft");

    const question = (await screen.findByText(/^4.4 is new, and version 2's 4.3/)).closest(
      "div.flex-col",
    )! as HTMLElement;
    expect(within(question).getByText("Against version 2's 4.3")).toBeInTheDocument();
    expect(
      within(question).getByText("after the end of the financial year", { selector: "ins" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Flag 3 asks whether 4.4 continues it.")).toBeInTheDocument();
    // 4.4's flag asks already, so only the other new clause offers the choice.
    expect(screen.getAllByRole("button", { name: "It's the same rule as…" })).toHaveLength(1);
    await userEvent.click(
      within(question).getByRole("button", { name: "It's the same rule as 4.3" }),
    );

    expect(
      await screen.findByText(/^Fixed: the same rule as 4.3, by Mariam Al Amiri/),
    ).toBeInTheDocument();
    expect(screen.getByText("Renumbered and reworded, was 4.3")).toBeInTheDocument();
    const sent = calls.find((call) => call.method === "POST")!;
    expect(sent.headers.get("If-Match")).toBe('"3"');
    expect(await sent.json()).toEqual({ continues: "data-retention:4.3" });

    // The decision can be taken back.
    const answered = screen
      .getByText(/^Fixed: the same rule as 4.3/)
      .closest("div.flex-col")! as HTMLElement;
    await userEvent.click(within(answered).getByRole("button", { name: "It's a different rule" }));
    expect(screen.getByRole("dialog", { name: "Is 4.4 a different rule?" })).toHaveTextContent(
      "If this is wrong, It's the same rule as… undoes it.",
    );
  });

  it("answers a question with a different rule at once, without asking again", async () => {
    const { calls } = serve({
      ...reviewing,
      "GET /v1/policies/data-retention/draft": { body: askingDraft },
      "POST /v1/policies/data-retention/draft/matches/data-retention%3A4.4/reject": {
        body: askingDraft,
      },
    });
    renderAt("/policies/data-retention/draft");

    const question = (await screen.findByText(/^4.4 is new, and version 2's 4.3/)).closest(
      "div.flex-col",
    )! as HTMLElement;
    await userEvent.click(within(question).getByRole("button", { name: "It's a different rule" }));

    expect(screen.queryByRole("dialog")).toBeNull();
    const sent = calls.find((call) => call.method === "POST")!;
    expect(sent.url).toContain("/matches/data-retention%3A4.4/reject");
    expect(sent.headers.get("If-Match")).toBe('"3"');
  });

  it("lets any new clause be said to be a rule nothing continues, closest first", async () => {
    const { calls } = serve({
      ...reviewing,
      "GET /v1/policies/data-retention/draft": { body: askingDraft },
      "POST /v1/policies/data-retention/draft/matches/data-retention%3A4.2": problem(
        "match-refused",
        409,
        { detail: "Version 2's 4.3 is continued by 4.4 already." },
      ),
    });
    renderAt("/policies/data-retention/draft");

    await userEvent.click(await screen.findByRole("button", { name: "It's the same rule as…" }));
    const chooser = screen.getByRole("dialog", {
      name: "Which rule of version 2 does 4.2 continue?",
    });
    const option = within(chooser).getByRole("radio", { name: /4.3\s*Few of its words/ });
    expect(option).toBeChecked();
    expect(chooser).toHaveTextContent(
      "4.2 becomes version 2's 4.3, renumbered and reworded. A citation of version 2's 4.3 will say its rule is 4.2 now.",
    );
    await userEvent.click(
      within(chooser).getByRole("button", { name: "It's the same rule as 4.3" }),
    );

    expect(
      await within(chooser).findByText("Version 2's 4.3 is continued by 4.4 already."),
    ).toBeInTheDocument();
    const sent = calls.find((call) => call.method === "POST")!;
    expect(await sent.json()).toEqual({ continues: "data-retention:4.3" });
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

describe("fixing what was read", () => {
  const FIXED_AT = new Date().toISOString();

  it("moves a heading under the one before when its flag suggests it", async () => {
    const [three, personalUse, ...rest] = acceptableUseDraft.clauses;
    const moved: PolicyDraft & { clause: string } = {
      ...acceptableUseDraft,
      revision: 2,
      clauses: [
        {
          ...three!,
          children: [
            ...three!.children,
            {
              ...personalUse!,
              key: "acceptable-use:3:personal-use",
              layer: "reviewer",
              fixed: "moved-under",
              children: personalUse!.children.map((child) => ({
                ...child,
                key: "acceptable-use:3:personal-use:p1",
              })),
            },
          ],
        },
        ...rest,
      ],
      flags: acceptableUseDraft.flags.map((found) =>
        found.position === 1
          ? {
              ...found,
              key: "acceptable-use:3:personal-use",
              suggestion: null,
              resolved_by: "Mariam Al Amiri",
              resolved_at: FIXED_AT,
              resolution: "moved-under",
              resolution_key: "acceptable-use:3",
            }
          : found,
      ),
      clause: "acceptable-use:3:personal-use",
    };
    const { calls } = serve({
      ...reviewing,
      "GET /v1/policies/acceptable-use/draft": { body: acceptableUseDraft },
      "POST /v1/policies/acceptable-use/draft/edits": { body: moved },
    });
    renderAt("/policies/acceptable-use/draft");

    const boundary = (await screen.findByText(/^"Personal use:" has no number/)).closest(
      "div.flex-col",
    )! as HTMLElement;
    await userEvent.click(within(boundary).getByRole("button", { name: "Move it under 3" }));

    expect(await screen.findByText(/^Fixed: moved under 3 by Mariam Al Amiri/)).toBeInTheDocument();
    const sent = calls.find((call) => call.method === "POST")!;
    expect(sent.headers.get("If-Match")).toBe('"1"');
    expect(await sent.json()).toEqual({ edit: "move-under", key: "acceptable-use:personal-use" });
    // The clause stays chosen under its new key, saying what was done to it.
    expect(screen.getByText("acceptable-use:3:personal-use")).toBeInTheDocument();
    expect(screen.getByText(/^A reviewer moved it under 3\./)).toBeInTheDocument();
    expect(screen.getByText("Moved under 3")).toBeInTheDocument();
  });

  it("splits a clause where the second rule begins", async () => {
    const { calls } = serve({
      ...reviewing,
      "GET /v1/policies/acceptable-use/draft": { body: acceptableUseDraft },
      "POST /v1/policies/acceptable-use/draft/edits": {
        body: { ...acceptableUseDraft, revision: 2, clause: "acceptable-use:4.1" },
      },
    });
    renderAt("/policies/acceptable-use/draft");

    await userEvent.click(await screen.findByRole("button", { name: /^4\.1\s*Acme records/ }));
    await userEvent.click(screen.getByRole("button", { name: "Split" }));

    const split = screen.getByRole("group", { name: "Split 4.1 where the second rule begins" });
    expect(split).toHaveTextContent("Split here");
    expect(split).toHaveTextContent("The second starts with a number, so its key is that number.");
    expect(within(split).getByText("The records are kept for 90 days.")).toBeInTheDocument();
    await userEvent.click(within(split).getByRole("button", { name: "Split it" }));

    const sent = calls.find((call) => call.method === "POST")!;
    expect(await sent.json()).toEqual({ edit: "split", key: "acceptable-use:4.1", at: 74 });
  });

  it("offers only the fixes a clause can take, and says why one was refused", async () => {
    serve({
      ...reviewing,
      "GET /v1/policies/acceptable-use/draft": { body: acceptableUseDraft },
      "POST /v1/policies/acceptable-use/draft/edits": problem("fix-refused", 409, {
        detail: "The clause before it is a heading: move this one under it instead.",
      }),
    });
    renderAt("/policies/acceptable-use/draft");

    await userEvent.click(
      await screen.findByRole("button", { name: /^personal-use\s*Personal use:/ }),
    );
    const tools = screen.getByRole("toolbar", { name: "Fix this clause" });
    expect(within(tools).getByRole("button", { name: "Split" })).toBeDisabled();
    expect(within(tools).getByRole("button", { name: "Move out a level" })).toBeDisabled();
    expect(within(tools).getByRole("button", { name: "Move under 3" })).toBeEnabled();
    expect(screen.getByRole("heading", { name: "Fixing what was read" })).toBeInTheDocument();

    await userEvent.click(within(tools).getByRole("button", { name: "Merge with the one before" }));

    expect(
      await screen.findByText(
        "That fix couldn't be made. The clause before it is a heading: move this one under it instead.",
      ),
    ).toBeInTheDocument();
  });
});
