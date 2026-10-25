import { describe, expect, it } from "vitest";

import { addDays, addMonths, isIsoDate, isMonth, mondayOf, monthGridRange, weekDays } from "../src/lib/calendarDates";
import { badgeKind } from "../src/features/calendar/status";

describe("calendar date maths", () => {
  it.each([
    ["2026-10-26", "2026-10-26"], // Monday
    ["2026-10-28", "2026-10-26"],
    ["2026-11-01", "2026-10-26"], // Sunday belongs to the week that started on Monday
    ["2027-01-01", "2026-12-28"], // across the year
  ])("mondayOf(%s) is %s", (day, monday) => {
    expect(mondayOf(day)).toBe(monday);
  });

  it("weekDays gives Monday to Sunday", () => {
    expect(weekDays("2026-10-24")).toEqual([
      "2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23", "2026-10-24", "2026-10-25",
    ]);
  });

  it("adds days across month ends and leap days", () => {
    expect(addDays("2026-10-31", 1)).toBe("2026-11-01");
    expect(addDays("2028-02-28", 1)).toBe("2028-02-29");
  });

  it.each([
    ["2026-10", 1, "2026-11"],
    ["2026-12", 1, "2027-01"],
    ["2026-01", -1, "2025-12"],
  ])("addMonths(%s, %i) is %s", (month, delta, expected) => {
    expect(addMonths(month, delta)).toBe(expected);
  });

  it.each([
    ["2026-10", "2026-09-28", "2026-11-01"], // 5 weeks
    ["2026-02", "2026-01-26", "2026-03-01"], // exactly 4 weeks
    ["2026-05", "2026-04-27", "2026-05-31"], // 5 weeks, ends on Sunday
    ["2027-01", "2026-12-28", "2027-01-31"],
  ])("month grid for %s runs %s to %s and fits the API's 42-day limit", (month, from, to) => {
    const range = monthGridRange(month);
    expect(range).toEqual({ from, to });
    const days = (Date.parse(to) - Date.parse(from)) / 86_400_000 + 1;
    expect(days % 7).toBe(0);
    expect(days).toBeLessThanOrEqual(42);
  });

  it("validates query params", () => {
    expect(isIsoDate("2026-02-30")).toBe(false);
    expect(isIsoDate("2026-02-28")).toBe(true);
    expect(isIsoDate(null)).toBe(false);
    expect(isMonth("2026-13")).toBe(false);
    expect(isMonth("2026-10")).toBe(true);
  });
});

describe("badgeKind", () => {
  it.each([
    ["rest", null, "rest"],
    ["missed", null, "missed"],
    ["done", 1, "done"],
    ["done", 0.6, "partial"],
    ["done", null, "done"],
    ["in_progress", 0.3, "partial"],
    ["planned", null, "planned"],
  ] as const)("%s with completion %s is %s", (status, completion, kind) => {
    expect(badgeKind(status, completion)).toBe(kind);
  });
});
