/**
 * Calendar-day arithmetic on `YYYY-MM-DD` strings (spec F9). Days are plain calendar dates in the
 * user's time zone, so the maths runs in UTC and never touches the device clock or zone.
 */

const DAY_MS = 86_400_000;

function toUtc(isoDate: string): number {
  const [y = 0, m = 1, d = 1] = isoDate.split("-").map(Number);
  return Date.UTC(y, m - 1, d);
}

function fromUtc(ms: number): string {
  return new Date(ms).toISOString().slice(0, 10);
}

export function addDays(isoDate: string, days: number): string {
  return fromUtc(toUtc(isoDate) + days * DAY_MS);
}

/** Monday of the ISO week containing `isoDate`. */
export function mondayOf(isoDate: string): string {
  const dow = new Date(toUtc(isoDate)).getUTCDay(); // 0 = Sunday
  return addDays(isoDate, -((dow + 6) % 7));
}

/** The 7 days Monday to Sunday of the week containing `isoDate`. */
export function weekDays(isoDate: string): string[] {
  const monday = mondayOf(isoDate);
  return Array.from({ length: 7 }, (_, i) => addDays(monday, i));
}

/** `YYYY-MM` of a day. */
export function monthOf(isoDate: string): string {
  return isoDate.slice(0, 7);
}

export function addMonths(month: string, delta: number): string {
  const [y = 0, m = 1] = month.split("-").map(Number);
  const index = y * 12 + (m - 1) + delta;
  return `${Math.floor(index / 12)}-${String((index % 12) + 1).padStart(2, "0")}`;
}

/** First and last day of the Monday-start grid covering `month` (35 or 42 days, never more). */
export function monthGridRange(month: string): { from: string; to: string } {
  const first = `${month}-01`;
  const last = addDays(`${addMonths(month, 1)}-01`, -1);
  return { from: mondayOf(first), to: addDays(mondayOf(last), 6) };
}

export function isMonth(value: string | null): value is string {
  return value !== null && /^\d{4}-(0[1-9]|1[0-2])$/.test(value);
}

export function isIsoDate(value: string | null): value is string {
  return value !== null && /^\d{4}-\d{2}-\d{2}$/.test(value) && fromUtc(toUtc(value)) === value;
}

const FORMATS = {
  weekday: { weekday: "long" },
  weekdayShort: { weekday: "short" },
  dayMonth: { day: "numeric", month: "short" },
  weekdayDayMonth: { weekday: "long", day: "numeric", month: "short" },
  weekdayDayMonthLong: { weekday: "long", day: "numeric", month: "long" },
  monthYear: { month: "long", year: "numeric" },
} satisfies Record<string, Intl.DateTimeFormatOptions>;

/** Names for `formatDay`, as identifiers so JSX call sites carry no string literals. */
export const DAY_FORMAT = {
  weekday: "weekday",
  weekdayShort: "weekdayShort",
  dayMonth: "dayMonth",
  weekdayDayMonth: "weekdayDayMonth",
  weekdayDayMonthLong: "weekdayDayMonthLong",
  monthYear: "monthYear",
} as const satisfies Record<keyof typeof FORMATS, keyof typeof FORMATS>;

/** Display helper: a day in the user's locale, formatted without any zone shift. */
export function formatDay(isoDate: string, locale: string, format: keyof typeof FORMATS): string {
  return new Intl.DateTimeFormat(locale, { ...FORMATS[format], timeZone: "UTC" }).format(toUtc(isoDate));
}
