import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { admin, catalog, role, roles } from "@/test/fixtures";
import { renderAt } from "@/test/render";
import { problem, serve } from "@/test/server";

const dpo = roles[1]!;

describe("a role", () => {
  it("saves a switched permission against the revision it was read at", async () => {
    const { calls } = serve({
      "GET /v1/sessions/current": { body: admin },
      "GET /v1/roles/r-dpo": { body: dpo },
      "GET /v1/permissions": { body: catalog },
      "PATCH /v1/roles/r-dpo": {
        body: { ...dpo, revision: 4, permissions: [...dpo.permissions, "queries.read_identities"] },
      },
    });
    renderAt("/users/roles/r-dpo");

    await userEvent.click(await screen.findByRole("switch", { name: "See who asked" }));
    expect(screen.getByText("1 change, not saved")).toBeInTheDocument();
    expect(screen.getByText(/See who asked: turned on\./)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    const saved = calls.find((call) => call.method === "PATCH")!;
    expect(saved.headers.get("If-Match")).toBe('"3"');
    expect((await saved.json()).permissions).toContain("queries.read_identities");
  });

  it("says who saved first, and keeps both changes when asked", async () => {
    const theirs = role({
      ...dpo,
      revision: 4,
      permissions: dpo.permissions.filter((key) => key !== "documents.publish"),
      updated_by: "Rami Aziz",
    });
    let reads = 0;
    let saves = 0;
    const { calls } = serve({
      "GET /v1/sessions/current": { body: admin },
      "GET /v1/roles/r-dpo": () => ({ body: reads++ === 0 ? dpo : theirs }),
      "GET /v1/permissions": { body: catalog },
      "PATCH /v1/roles/r-dpo": () =>
        saves++ === 0
          ? problem("edit-conflict", 412, {
              revision: 4,
              updated_by: "Rami Aziz",
              updated_at: new Date().toISOString(),
            })
          : { body: { ...theirs, revision: 5 } },
    });
    renderAt("/users/roles/r-dpo");

    await userEvent.click(await screen.findByRole("switch", { name: "See who asked" }));
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    const dialog = await screen.findByRole("dialog", { name: "Someone changed this role" });
    expect(dialog).toHaveTextContent("Rami Aziz changed DPO today at");
    expect(dialog).toHaveTextContent("Their change: Publish policies: turned off.");
    await userEvent.click(within(dialog).getByRole("button", { name: "Keep both changes" }));

    const second = calls.filter((call) => call.method === "PATCH")[1]!;
    expect(second.headers.get("If-Match")).toBe('"4"');
    const sent: string[] = (await second.json()).permissions;
    expect(sent).toContain("queries.read_identities");
    expect(sent).not.toContain("documents.publish");
  });

  it("explains a change that would leave nobody able to manage roles", async () => {
    const adminRole = roles[0]!;
    serve({
      "GET /v1/sessions/current": { body: admin },
      "GET /v1/roles/r-admin": { body: adminRole },
      "GET /v1/permissions": { body: catalog },
      "PATCH /v1/roles/r-admin": problem("lockout-refused", 409),
    });
    renderAt("/users/roles/r-admin");

    await userEvent.click(await screen.findByRole("switch", { name: "Manage roles" }));
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This would leave nobody who can manage roles.",
    );
  });

  it("will not offer to delete a role somebody holds", async () => {
    serve({
      "GET /v1/sessions/current": { body: admin },
      "GET /v1/roles/r-dpo": { body: dpo },
      "GET /v1/permissions": { body: catalog },
    });
    renderAt("/users/roles/r-dpo");

    expect(await screen.findByRole("button", { name: "Delete DPO" })).toBeDisabled();
    expect(screen.getByText(/Mariam Al Amiri holds this one/)).toBeInTheDocument();
  });
});
