import { describe, expect, it } from "vitest";

import { endsToday, paramsFromPeriod, periodDays, periodFromParams, presetPeriod, stepPeriod, validateRange } from "../src/features/charts/period";

const TODAY = "2026-10-26";
const q = (s: string) => new URLSearchParams(s);

describe("period helpers (F15.7)", () => {
  it("counts days with both bounds included", () => {
    expect(periodDays("2026-10-26", "2026-10-26")).toBe(1);
    expect(periodDays("2026-09-27", "2026-10-26")).toBe(30);
  });

  it("builds each preset ending today with its length", () => {
    expect(presetPeriod("7d", TODAY)).toEqual({ from: "2026-10-20", to: TODAY, kind: "7d" });
    for (const [key, days] of [["30d", 30], ["90d", 90], ["6m", 182], ["1y", 364]] as const) {
      const p = presetPeriod(key, TODAY);
      expect([p.to, periodDays(p.from, p.to)]).toEqual([TODAY, days]);
    }
  });

  it.each([
    ["2026-10-01", "2026-10-10", null],
    ["2026-10-10", "2026-10-10", null],
    ["2026-10-11", "2026-10-10", "order"],
    ["2026-10-01", "2026-10-27", "future"],
    ["2025-10-21", "2026-10-26", null], // 371 days
    ["2025-10-20", "2026-10-26", "tooLong"], // 372 days
    ["", "2026-10-10", "missing"],
    ["2026-13-01", "2026-10-10", "missing"],
  ])("validates %s .. %s as %s", (from, to, expected) => {
    expect(validateRange(from, to, TODAY)).toBe(expected);
  });

  it("reads the period from the URL and falls back to 30 days", () => {
    expect(periodFromParams(q(""), TODAY).kind).toBe("30d");
    expect(periodFromParams(q("period=90d"), TODAY).kind).toBe("90d");
    expect(periodFromParams(q("period=nope"), TODAY).kind).toBe("30d");
    expect(periodFromParams(q("from=2026-10-01&to=2026-10-10"), TODAY)).toEqual({ from: "2026-10-01", to: "2026-10-10", kind: "custom" });
    expect(periodFromParams(q("from=2026-10-10&to=2026-10-01"), TODAY).kind).toBe("30d");
    expect(periodFromParams(q("from=2026-10-01"), TODAY).kind).toBe("30d"); // both or neither
    expect(periodFromParams(q("from=2026-10-01&to=2026-12-01"), TODAY).kind).toBe("30d"); // after today
  });

  it("round-trips through the URL", () => {
    for (const search of ["period=6m", "from=2026-10-01&to=2026-10-10"]) {
      const p = periodFromParams(q(search), TODAY);
      expect(periodFromParams(new URLSearchParams(paramsFromPeriod(p)), TODAY)).toEqual(p);
    }
  });

  it("steps by the range length and never past today", () => {
    const week = presetPeriod("7d", TODAY);
    const back = stepPeriod(week, -1, TODAY);
    expect(back).toEqual({ from: "2026-10-13", to: "2026-10-19", kind: "custom" });
    expect(stepPeriod(back, 1, TODAY)).toEqual(week); // a preset length ending today is the preset again
    const old = { from: "2026-10-01", to: "2026-10-20", kind: "custom" as const }; // 20 days
    expect(stepPeriod(old, 1, TODAY)).toEqual({ from: "2026-10-07", to: TODAY, kind: "custom" }); // moved back, ends today
    expect(endsToday(week, TODAY)).toBe(true);
    expect(endsToday(back, TODAY)).toBe(false);
  });
});
