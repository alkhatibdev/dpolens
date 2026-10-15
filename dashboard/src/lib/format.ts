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

const times = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit" });
const dayAndMonth = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short" });
const weekdayAndDate = new Intl.DateTimeFormat("en-GB", {
  weekday: "short",
  day: "numeric",
  month: "short",
});
const fullDay = new Intl.DateTimeFormat("en-GB", {
  weekday: "long",
  day: "numeric",
  month: "long",
});
const ago = new Intl.RelativeTimeFormat("en-GB", { numeric: "always" });

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

function sameDay(a: Date, b: Date): boolean {
  return a.toDateString() === b.toDateString();
}

/** A moment in the reader's own time zone, such as "3 Oct at 16:20". */
export function formatMoment(iso: string): string {
  const when = new Date(iso);
  return `${dayAndMonth.format(when)} at ${times.format(when)}`;
}

/** "today at 09:12", or "on 3 Oct at 16:20", to follow a verb such as "changed". */
export function formatWhen(iso: string, now: Date = new Date()): string {
  const when = new Date(iso);
  return sameDay(when, now) ? `today at ${times.format(when)}` : `on ${formatMoment(iso)}`;
}

/** "Saturday 18 October at 09:05", for a deadline someone has to meet. */
export function formatDeadline(iso: string): string {
  const when = new Date(iso);
  return `${fullDay.format(when)} at ${times.format(when)}`;
}

/** "Sat 18 Oct", for when a link or a token runs out. */
export function formatWeekday(iso: string): string {
  return weekdayAndDate.format(new Date(iso));
}

/** How long ago, in the words a person uses: "4 minutes ago", "Yesterday, 23:10". */
export function formatSince(iso: string, now: Date = new Date()): string {
  const when = new Date(iso);
  const elapsed = now.getTime() - when.getTime();
  if (elapsed < MINUTE) {
    return "Just now";
  }
  if (elapsed < HOUR) {
    return capitalise(ago.format(-Math.floor(elapsed / MINUTE), "minute"));
  }
  if (sameDay(when, now)) {
    return capitalise(ago.format(-Math.floor(elapsed / HOUR), "hour"));
  }
  if (sameDay(when, new Date(now.getTime() - DAY))) {
    return `Yesterday, ${times.format(when)}`;
  }
  if (elapsed < 14 * DAY) {
    return capitalise(ago.format(-Math.max(2, Math.floor(elapsed / DAY)), "day"));
  }
  if (elapsed < 9 * 7 * DAY) {
    return capitalise(ago.format(-Math.floor(elapsed / (7 * DAY)), "week"));
  }
  return formatDate(iso, "short");
}

/** Whole days until a moment, rounding up, so tomorrow at any hour is 1. */
export function daysUntil(iso: string, now: Date = new Date()): number {
  return Math.ceil((new Date(iso).getTime() - now.getTime()) / DAY);
}

function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}
