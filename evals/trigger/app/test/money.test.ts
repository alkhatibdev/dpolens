import { describe, expect, it } from "vitest";
import { formatPrice, orderTotal } from "../src/lib/money.js";

describe("formatPrice", () => {
  it("shows pence as pounds", () => {
    expect(formatPrice(1250)).toBe("£12.50");
  });
});

describe("orderTotal", () => {
  it("adds up every line", () => {
    expect(
      orderTotal([
        { priceCents: 250, quantity: 2 },
        { priceCents: 100, quantity: 1 },
      ]),
    ).toBe(600);
  });
});
