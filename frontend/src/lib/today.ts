/** Today's calendar day in an IANA time zone, ready to display (spec §6.2, F9.1). */
export interface LocalDay {
  /** `YYYY-MM-DD` of the day in `timeZone`, for `<time dateTime>`. */
  isoDate: string;
  /** e.g. "Friday". */
  weekday: string;
  /** e.g. "23 October 2026" (order and wording follow `locale`). */
  date: string;
}

function formatterFor(locale: string, timeZone: string, options: Intl.DateTimeFormatOptions) {
  try {
    return new Intl.DateTimeFormat(locale, { ...options, timeZone });
  } catch {
    // An unknown zone name throws RangeError. The API only stores valid IANA names, so this is a
    // safety net: fall back to UTC (the storage zone) rather than crash the page.
    return new Intl.DateTimeFormat(locale, { ...options, timeZone: "UTC" });
  }
}

/** The day it is at instant `now` in `timeZone`. Pure: the caller passes the clock. */
export function localDay(now: Date, timeZone: string, locale: string): LocalDay {
  const isoParts = formatterFor("en-CA", timeZone, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(now);
  const part = (type: Intl.DateTimeFormatPartTypes) => isoParts.find((p) => p.type === type)?.value ?? "";

  return {
    isoDate: `${part("year")}-${part("month")}-${part("day")}`,
    weekday: formatterFor(locale, timeZone, { weekday: "long" }).format(now),
    date: formatterFor(locale, timeZone, { day: "numeric", month: "long", year: "numeric" }).format(now),
  };
}
