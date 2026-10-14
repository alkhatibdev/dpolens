const dates = {
  long: new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "long", year: "numeric" }),
  short: new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric" }),
};

/**
 * "2022-01-02" as "2 January 2022", or "2 Jan 2022" where space is tight, read as
 * a calendar date and never shifted by a time zone.
 */
export function formatDate(iso: string, length: "long" | "short" = "long"): string {
  const [year, month, day] = iso.slice(0, 10).split("-").map(Number);
  return dates[length].format(new Date(Date.UTC(year ?? 1970, (month ?? 1) - 1, day ?? 1)));
}

/** A language's name in English, such as "Arabic" for "ar". */
export function languageName(code: string): string {
  return new Intl.DisplayNames(["en"], { type: "language" }).of(code) ?? code;
}

/** A language's name in itself, such as "العربية" for "ar". */
export function nativeLanguageName(code: string): string {
  return new Intl.DisplayNames([code], { type: "language" }).of(code) ?? code;
}

export function isRightToLeft(code: string): boolean {
  return ["ar", "fa", "he", "ur"].includes(code.split("-")[0] ?? code);
}

/** Left to right languages first, so Arabic sits on the far side, as on the page of the law. */
export function readingOrder(languages: readonly string[]): string[] {
  return [...languages].sort((a, b) => Number(isRightToLeft(a)) - Number(isRightToLeft(b)));
}
