import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "../src/i18n/en.json";
import { localDay } from "../src/lib/today";
import { meFixture, meOk } from "./mocks/fixtures";
import { server } from "./mocks/server";
import { renderApp } from "./renderApp";

// 23:30 UTC on Friday 23 October 2026: already Saturday the 24th in Auckland (UTC+13),
// still Friday in Los Angeles (UTC−7).
const LATE_FRIDAY_UTC = new Date("2026-10-23T23:30:00Z");
// 03:00 UTC on Saturday 24 October: still Friday the 23rd in Los Angeles.
const EARLY_SATURDAY_UTC = new Date("2026-10-24T03:00:00Z");

describe("localDay", () => {
  it.each<[Date, string, string, string, string]>([
    [LATE_FRIDAY_UTC, "UTC", "2026-10-23", "Friday", "October 23, 2026"],
    [LATE_FRIDAY_UTC, "Pacific/Auckland", "2026-10-24", "Saturday", "October 24, 2026"],
    [EARLY_SATURDAY_UTC, "UTC", "2026-10-24", "Saturday", "October 24, 2026"],
    [EARLY_SATURDAY_UTC, "America/Los_Angeles", "2026-10-23", "Friday", "October 23, 2026"],
    [new Date("2026-12-31T23:30:00Z"), "Asia/Tokyo", "2027-01-01", "Friday", "January 1, 2027"],
  ])("%s in %s is %s (%s)", (now, zone, isoDate, weekday, date) => {
    expect(localDay(now, zone, "en")).toEqual({ isoDate, weekday, date });
  });

  it("falls back to UTC for an unknown zone instead of throwing", () => {
    expect(localDay(LATE_FRIDAY_UTC, "Not/AZone", "en").isoDate).toBe("2026-10-23");
  });
});

describe("Today page", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows the display name and today's date in the user's time zone, not UTC", async () => {
    // Only Date is faked: MSW and React Query keep real timers.
    vi.useFakeTimers({ toFake: ["Date"], now: LATE_FRIDAY_UTC });
    server.use(meOk(meFixture({ display_name: "Ana", timezone: "Pacific/Auckland" })));

    renderApp("/today");

    expect(await screen.findByText("Hi, Ana")).toBeInTheDocument();
    const heading = screen.getByRole("heading", { level: 1 });
    // In UTC it is still Friday 23 October; in Auckland it is Saturday the 24th.
    expect(heading).toHaveTextContent("Saturday");
    expect(heading).toHaveTextContent("October 24, 2026");
    expect(heading).not.toHaveTextContent("Friday");
    expect(heading.querySelector("time")).toHaveAttribute("datetime", "2026-10-24");
  });

  it("uses the zone west of UTC as well (still yesterday)", async () => {
    vi.useFakeTimers({ toFake: ["Date"], now: EARLY_SATURDAY_UTC });
    server.use(meOk(meFixture({ timezone: "America/Los_Angeles" })));

    renderApp("/today");

    const heading = await screen.findByRole("heading", { level: 1 });
    expect(heading).toHaveTextContent("Friday");
    expect(heading).toHaveTextContent("October 23, 2026");
  });

  it.each<["athlete" | "coach", string]>([
    ["coach", en.today.placeholder.coach],
  ])("shows the M1 placeholder for a %s", async (role, text) => {
    server.use(meOk(meFixture({ role })));

    renderApp("/today");

    expect(await screen.findByText(text)).toBeInTheDocument();
  });
});
