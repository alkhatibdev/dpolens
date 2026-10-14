import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { article13 } from "@/test/fixtures";

import { Reading } from "./Reading";

const writeText = vi.fn(async () => {});

beforeEach(() => {
  writeText.mockClear();
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  Object.defineProperty(window, "isSecureContext", { value: true, configurable: true });
});

describe("reading a clause in two languages", () => {
  it("sets Arabic right to left, in its own language, beside the English", () => {
    render(<Reading byLanguage={article13} languages={["ar", "en"]} breadcrumb={[]} />);

    const arabic = screen.getByText(/يحق لصاحب البيانات/);
    expect(arabic).toHaveAttribute("lang", "ar");
    expect(arabic).toHaveAttribute("dir", "rtl");
    expect(screen.getByText(/The Data Subject has the right/)).toHaveAttribute("dir", "ltr");
  });

  it("copies a clause with the citation an assistant would give", async () => {
    render(<Reading byLanguage={article13} languages={["ar", "en"]} breadcrumb={[]} />);

    await userEvent.click(
      screen.getByRole("button", { name: "Copy the citation uae-pdpl:art-13:para-1" }),
    );

    const copied = String(writeText.mock.calls[0]?.at(0));
    expect(copied).toContain("The Data Subject has the right");
    expect(copied).toContain(
      "Article (13) Right to Receive Information > 1 (uae-pdpl:art-13:para-1)",
    );
    expect(await screen.findByText("Copied")).toBeInTheDocument();
  });

  it("leaves out clauses with no words of their own", () => {
    render(<Reading byLanguage={article13} languages={["ar", "en"]} breadcrumb={[]} />);

    expect(screen.queryByRole("button", { name: /uae-pdpl:art-13$/ })).not.toBeInTheDocument();
  });
});
