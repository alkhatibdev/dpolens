import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { dpo, entry, yousef } from "@/test/fixtures";
import { renderAt } from "@/test/render";
import { serve } from "@/test/server";

const entries = [
  entry({
    seq: 1202,
    action: "pat.rejected",
    target_type: "personal_access_token",
    target_id: "t-ci",
    details: { reason: "revoked", prefix: "dpol_9fQe2b", via: "api" },
    actor_token: { id: "t-ci", name: "ci-runner", prefix: "dpol_9fQe2b", owner: "Omar Khalil" },
    target_token: { id: "t-ci", name: "ci-runner", prefix: "dpol_9fQe2b", owner: "Omar Khalil" },
  }),
  entry({
    seq: 1200,
    action: "role.permissions_changed",
    target_type: "role",
    target_id: "DPO",
    actor: yousef,
    details: {
      granted: ["queries.read_identities"],
      revoked: [],
      before: ["documents.read", "queries.read_all"],
      after: ["documents.read", "queries.read_all", "queries.read_identities"],
      via: "dashboard",
    },
  }),
  entry({
    seq: 1194,
    action: "laws.selected",
    target_type: "selected_laws",
    target_id: "instance",
    details: {
      before: null,
      after: ["gdpr", "uae-pdpl"],
      via: "cli",
      actor: { os_user: "deploy", host: "dpolens-prod" },
    },
  }),
];

const routes = {
  "GET /v1/sessions/current": { body: dpo },
  "GET /v1/governance/entries": { body: { entries, total: 3, next: null } },
  "GET /v1/governance/actors": { body: { people: [yousef] } },
};

describe("the governance log", () => {
  it("says what happened in plain words, and who did it", async () => {
    serve({
      ...routes,
      "GET /v1/governance/verification": {
        body: {
          ok: true,
          entries: 1204,
          first_broken_seq: null,
          reason: null,
          out_of_order: [],
          anchored_to_genesis: true,
          checked_at: new Date().toISOString(),
        },
      },
    });
    renderAt("/logs/governance");

    expect(await screen.findByText("The record is intact")).toBeInTheDocument();
    expect(await screen.findByText("1,204 entries")).toBeInTheDocument();
    expect(
      screen.getByText(/Refused Omar Khalil's token ci-runner, because it is revoked/),
    ).toBeInTheDocument();
    expect(screen.getByText("Gave DPO the permission to see who asked")).toBeInTheDocument();
    const chosen = screen.getByText("Chose the laws that apply: GDPR, UAE PDPL").closest("tr")!;
    expect(within(chosen).getByText("Command line")).toBeInTheDocument();
    expect(within(chosen).getByText("deploy on dpolens-prod")).toBeInTheDocument();

    const changed = screen.getByText("Gave DPO the permission to see who asked").closest("tr")!;
    await userEvent.click(within(changed).getByRole("button", { name: "Show what changed" }));
    expect(screen.getByText("Before")).toBeInTheDocument();
    expect(screen.getByText("After")).toBeInTheDocument();
  });

  it("says plainly when the record does not check out", async () => {
    serve({
      ...routes,
      "GET /v1/governance/verification": {
        body: {
          ok: false,
          entries: 1204,
          first_broken_seq: 412,
          reason: "the entry's fields do not match its own hash",
          out_of_order: [],
          anchored_to_genesis: true,
          checked_at: new Date().toISOString(),
        },
      },
    });
    renderAt("/logs/governance");

    expect(await screen.findByText("The record does not check out")).toBeInTheDocument();
    expect(
      screen.getByText(/Entry 412: the entry's fields do not match its own hash/),
    ).toBeInTheDocument();
  });
});
