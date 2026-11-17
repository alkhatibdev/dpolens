import { beforeEach, describe, expect, it } from "vitest";

import { reloadTarget } from "./upgrade";

const CURRENT = "https://dpolens.example/library?law=gdpr";

describe("reloadTarget", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
  });

  const storage = () => window.sessionStorage;

  it("loads the page somebody was opening", () => {
    const opening = { pathname: "/clauses/gdpr-art-5", search: "?lang=en", hash: "#p-1" };
    expect(reloadTarget(opening, CURRENT, storage, 1_000_000)).toBe(
      "/clauses/gdpr-art-5?lang=en#p-1",
    );
  });

  it("loads the page that is open when nobody was going anywhere", () => {
    expect(reloadTarget(undefined, CURRENT, storage, 1_000_000)).toBe(CURRENT);
  });

  it("leaves the error showing when a file is still missing right after a load", () => {
    expect(reloadTarget(undefined, CURRENT, storage, 1_000_000)).toBe(CURRENT);
    expect(reloadTarget(undefined, CURRENT, storage, 1_009_999)).toBeNull();
  });

  it("tries again once the pause has passed", () => {
    expect(reloadTarget(undefined, CURRENT, storage, 1_000_000)).toBe(CURRENT);
    expect(reloadTarget(undefined, CURRENT, storage, 1_010_000)).toBe(CURRENT);
  });

  it("does not reload where the attempt cannot be noted", () => {
    const blocked = () => {
      throw new DOMException("The operation is insecure.", "SecurityError");
    };
    expect(reloadTarget(undefined, CURRENT, blocked, 1_000_000)).toBeNull();
  });
});
