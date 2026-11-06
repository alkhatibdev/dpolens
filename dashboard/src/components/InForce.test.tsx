import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { article13 } from "@/test/fixtures";

import { ComingWords, InForce } from "./InForce";

const paragraph = article13.en[1]!;

describe("when a clause applies", () => {
  it("says since when on its own page, and nothing in a result while nothing will change", () => {
    const { container } = render(<InForce clause={paragraph} />);
    expect(container).toBeEmptyDOMElement();

    render(<InForce clause={paragraph} always />);
    expect(screen.getByText("In force since 2 January 2022")).toBeInTheDocument();
  });

  it("marks a provision that starts later, so a duty can be prepared for", () => {
    render(<InForce clause={{ ...paragraph, in_force: false, in_force_from: "2999-05-13" }} />);

    expect(screen.getByText("In force from 13 May 2999")).toBeInTheDocument();
  });

  it("says when no day has been set", () => {
    render(<InForce clause={{ ...paragraph, in_force: false, in_force_from: null }} />);

    expect(screen.getByText("Not in force yet: no date set")).toBeInTheDocument();
  });

  it("says when its words stop applying, and once they have", () => {
    render(<InForce clause={{ ...paragraph, in_force_until: "2999-05-13" }} />);
    expect(screen.getByText("In force until 13 May 2999")).toBeInTheDocument();

    render(<InForce clause={{ ...paragraph, in_force: false, in_force_until: "2025-06-01" }} />);
    expect(screen.getByText("No longer in force since 1 June 2025")).toBeInTheDocument();
  });

  it("tells a result that an amendment gives it new words", () => {
    const coming = {
      heading: null,
      text: "Personal data shall be kept no longer than twelve months.",
      in_force_from: "2999-01-17",
      dates_set_by: "Act No. 56 of 2026",
    };
    render(<InForce clause={{ ...paragraph, coming }} />);

    expect(screen.getByText("New words from 17 January 2999")).toBeInTheDocument();
  });
});

describe("the words an amendment brings", () => {
  it("are quoted in their own language, with the day and what set it", () => {
    render(
      <ComingWords
        lang="ar"
        coming={{
          heading: null,
          text: "لا تحفظ البيانات الشخصية أكثر من اثني عشر شهرا.",
          in_force_from: "2999-01-17",
          dates_set_by: "قانون رقم 56 لسنة 2026",
        }}
      />,
    );

    expect(
      screen.getByText("From 17 January 2999, an amendment gives it these words:"),
    ).toBeInTheDocument();
    expect(screen.getByText(/لا تحفظ البيانات/)).toHaveAttribute("dir", "rtl");
    expect(screen.getByText("Set by قانون رقم 56 لسنة 2026")).toBeInTheDocument();
  });
});
