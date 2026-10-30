import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { components } from "../src/api/schema";
import { displayWeight, percent } from "../src/features/charts/chartData";
import { meFixture, meOk, problem } from "./mocks/fixtures";
import { apiUrl } from "./mocks/handlers";
import { server } from "./mocks/server";
import { renderApp } from "./renderApp";

type Schemas = components["schemas"];

// Monday 26 Oct 2026, 10:00 UTC: "today" is 2026-10-26 in Madrid.
const NOW = new Date("2026-10-26T10:00:00Z");
const ME = meFixture();
const A = `/athletes/${ME.id}/charts`;

const bench: Schemas["ExerciseSummary"] = {
  id: "ex-bench",
  name: "Bench press",
  type: "strength",
  equipment: "barbell",
  muscle_group: "chest",
};

const set = (over: Partial<Schemas["SessionChartSet"]>): Schemas["SessionChartSet"] => ({
  set_no: 1,
  status: "met",
  completion: 1,
  target_reps: 8,
  target_weight_kg: 100,
  target_seconds: null,
  reps: 8,
  weight_kg: 100,
  seconds: null,
  ...over,
});

const sessionChart = (): Schemas["SessionChart"] => ({
  session_id: "s-1",
  date: "2026-10-24",
  training_day_name: "Push",
  status: "done",
  completion: 0.7,
  kcal: 320,
  exercises: [
    {
      exercise: bench,
      is_extra: false,
      completion: 0.7,
      sets: [
        set({ set_no: 1, status: "met" }),
        set({ set_no: 2, status: "partial", completion: 0.75, reps: 6 }),
        set({ set_no: 3, status: "missed", completion: 0, reps: null, weight_kg: null }),
        set({ set_no: 4, status: "skipped", completion: null, reps: null, weight_kg: null }),
        set({ set_no: 5, status: "extra", completion: null, target_reps: null, target_weight_kg: null, reps: 5, weight_kg: 60 }),
      ],
    },
  ],
});

const point = (over: Partial<Schemas["ExerciseChartPoint"]>): Schemas["ExerciseChartPoint"] => ({
  date: "2026-10-12",
  session_id: "s-1",
  target_weight_kg: 100,
  target_reps: 8,
  target_seconds: null,
  top_set_weight_kg: 100,
  top_set_reps: 8,
  top_set_seconds: null,
  volume_kg: 2400,
  is_pr: false,
  ...over,
});

const exerciseChart = (weeks: 4 | 12 | 26 | 52 = 12, points = [point({}), point({ date: "2026-10-19", top_set_weight_kg: 102.5, is_pr: true })]): Schemas["ExerciseChart"] => ({
  exercise: bench,
  weeks,
  points,
});

const day = (date: string, over: Partial<Schemas["AdherenceDay"]> = {}): Schemas["AdherenceDay"] => ({
  date,
  training_status: "rest",
  training_completion: null,
  nutrition_completion: null,
  ...over,
});

const adherence = (): Schemas["AdherenceChart"] => ({
  from: "2026-09-28",
  to: "2026-11-01",
  days: [
    day("2026-09-28", { training_status: "done", training_completion: 1, nutrition_completion: 0.9 }),
    day("2026-09-29"), // rest
    day("2026-09-30", { training_status: "missed", training_completion: 0 }),
    day("2026-10-01", { training_status: "planned" }),
  ],
  weeks: [
    { week_start: "2026-09-28", sessions_planned: 2, sessions_done: 1, training_completion: 0.5, nutrition_completion: 0.9 },
  ],
});

const dv = (date: string, value: number | null) => ({ date, value });

const weekly = (over: Partial<Schemas["WeeklySummary"]> = {}): Schemas["WeeklySummary"] => ({
  week_start: "2026-10-26",
  week_end: "2026-11-01",
  estimated: true,
  sessions_planned: 4,
  sessions_done: 3,
  sessions_missed: 1,
  avg_completion: 0.82,
  avg_daily_balance_kcal: -350,
  target_daily_balance_kcal: -400,
  weight_avg_start_kg: 80,
  weight_avg_end_kg: 79.5,
  weight_change_kg: -0.5,
  sparklines: {
    daily_balance_kcal: [dv("2026-10-26", -300), dv("2026-10-27", -400)],
    training_completion: [dv("2026-10-26", 1), dv("2026-10-27", null)],
    weight_avg_kg: [dv("2026-10-26", 80), dv("2026-10-27", 79.5)],
  },
  ...over,
});

const body = (points: Schemas["BodyChartPoint"][] = [
  { date: "2026-10-20", weight_kg: 80, weight_avg_7d_kg: 80, body_fat_pct: 18.5 },
  { date: "2026-10-26", weight_kg: 79.5, weight_avg_7d_kg: 79.75, body_fat_pct: null },
]): Schemas["BodyChart"] => ({ weeks: 12, estimated: true, points });

/** Records the `weeks` query values of a chart endpoint. */
function serve(path: string, respond: (weeks: number | null) => Response | Promise<Response>, seen: (string | null)[] = []) {
  server.use(
    http.get(apiUrl(path), ({ request }) => {
      const w = new URL(request.url).searchParams.get("weeks");
      seen.push(w);
      return respond(w === null ? null : Number(w));
    }),
  );
  return seen;
}

function serveAll(over: { adherence?: Schemas["AdherenceChart"]; body?: Schemas["BodyChart"]; weekly?: Schemas["WeeklySummary"] } = {}) {
  server.use(
    http.get(apiUrl(`${A}/weekly-summary`), () => HttpResponse.json(over.weekly ?? weekly())),
    http.get(apiUrl(`${A}/adherence`), () => HttpResponse.json(over.adherence ?? adherence())),
    http.get(apiUrl(`${A}/body`), () => HttpResponse.json(over.body ?? body())),
  );
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"], now: NOW });
  server.use(meOk());
});
afterEach(() => vi.useRealTimers());

describe("chart helpers", () => {
  it("keeps null completion null and 0 as 0", () => {
    expect(percent(null)).toBeNull();
    expect(percent(0)).toBe(0);
    expect(percent(0.456)).toBe(46);
  });
  it("converts kg only for imperial users", () => {
    expect(displayWeight(100, "metric")).toBe(100);
    expect(displayWeight(100, "imperial")).toBe(220.5);
    expect(displayWeight(null, "imperial")).toBeNull();
  });
});

describe("Session view", () => {
  it("shows set status markers and completion per set", async () => {
    server.use(http.get(apiUrl(`${A}/session/s-1`), () => HttpResponse.json(sessionChart())));
    renderApp("/progress/session/s-1");
    const rows = await screen.findAllByTestId("set-row");
    expect(rows.map((r) => r.getAttribute("data-status"))).toEqual(["met", "partial", "missed", "skipped", "extra"]);
    expect(within(rows[0]!).getByText("✓")).toBeInTheDocument();
    expect(within(rows[1]!).getByText("⚠")).toBeInTheDocument();
    expect(within(rows[1]!).getByText("Partial")).toBeInTheDocument();
    expect(within(rows[1]!).getByText("75%")).toBeInTheDocument();
    expect(within(rows[2]!).getByText("0%")).toBeInTheDocument(); // missed is a real 0 %
    expect(within(rows[3]!).queryByText(/%/)).not.toBeInTheDocument(); // skipped: null, no number
    expect(screen.getByRole("img", { name: /Target versus actual per set for Bench press/ })).toBeInTheDocument();
  });

  it("shows an empty state when nothing was logged", async () => {
    server.use(http.get(apiUrl(`${A}/session/s-1`), () => HttpResponse.json({ ...sessionChart(), exercises: [] })));
    renderApp("/progress/session/s-1");
    expect(await screen.findByText("No sets were logged in this session.")).toBeInTheDocument();
  });

  it("shows the forbidden state on 403 not_linked", async () => {
    server.use(http.get(apiUrl(`${A}/session/s-1`), () => problem(403, "not_linked")));
    renderApp("/progress/session/s-1");
    expect(await screen.findByText("You don't have access to this data.")).toBeInTheDocument();
  });

  it("shows weights in lb to an imperial user", async () => {
    server.use(meOk(meFixture({ units: "imperial" })), http.get(apiUrl(`${A}/session/s-1`), () => HttpResponse.json(sessionChart())));
    renderApp("/progress/session/s-1");
    const rows = await screen.findAllByTestId("set-row");
    expect(rows[0]).toHaveTextContent("220.5 of 220.5 lb");
    expect(rows[0]).not.toHaveTextContent(/\b100 /);
  });
});

describe("Exercise view", () => {
  async function pickBench(user = userEvent.setup()) {
    server.use(
      http.get(apiUrl("/exercises"), () => HttpResponse.json({ items: [{ ...bench, description: null, is_custom: false }], next_cursor: null })),
    );
    renderApp("/progress");
    await user.type(await screen.findByLabelText("Search an exercise"), "ben");
    await user.click(await screen.findByRole("button", { name: "Bench press" }));
    return user;
  }

  it("offers exactly 4/12/26/52 weeks and sends the chosen value", async () => {
    serveAll();
    const seen = serve(`${A}/exercise/ex-bench`, (w) => HttpResponse.json(exerciseChart((w ?? 12) as 12)));
    const user = await pickBench();
    const section = screen.getByRole("region", { name: "Exercise over time" });
    await waitFor(() => expect(seen).toEqual(["12"]));
    const radios = within(section).getAllByRole("radio");
    expect(radios.map((r) => (r as HTMLInputElement).value)).toEqual(["4", "12", "26", "52"]);
    await user.click(within(section).getByLabelText("26 weeks"));
    await waitFor(() => expect(seen).toContain("26"));
    await user.click(within(section).getByLabelText("4 weeks"));
    await waitFor(() => expect(seen).toContain("4"));
  });

  it("marks only personal-record points and shows volume", async () => {
    serveAll();
    serve(`${A}/exercise/ex-bench`, () => HttpResponse.json(exerciseChart()));
    await pickBench();
    expect(await screen.findAllByTestId("pr-marker")).toHaveLength(1);
    expect(screen.getByTestId("pr-list")).toHaveTextContent("Oct 19 (102.5 kg)");
    expect(screen.getByRole("img", { name: /Volume per session for Bench press/ })).toBeInTheDocument();
  });

  it("converts to lb for an imperial user", async () => {
    server.use(meOk(meFixture({ units: "imperial" })));
    serveAll();
    serve(`${A}/exercise/ex-bench`, () => HttpResponse.json(exerciseChart()));
    await pickBench();
    expect(await screen.findByTestId("pr-list")).toHaveTextContent("(226 lb)");
    expect(screen.getByRole("img", { name: /Target and top-set weight for Bench press in lb/ })).toBeInTheDocument();
  });

  it("shows an empty state without points", async () => {
    serveAll();
    serve(`${A}/exercise/ex-bench`, () => HttpResponse.json(exerciseChart(12, [])));
    await pickBench();
    expect(await screen.findByText("No finished sessions with this exercise in this range.")).toBeInTheDocument();
  });

  it("shows the forbidden state on 403 not_linked", async () => {
    serveAll();
    serve(`${A}/exercise/ex-bench`, () => problem(403, "not_linked"));
    await pickBench();
    expect(await screen.findByText("You don't have access to this data.")).toBeInTheDocument();
  });
});

describe("Adherence", () => {
  it("renders null completion neutral and a missed session as 0 %", async () => {
    serveAll();
    renderApp("/progress");
    const cells = await screen.findAllByTestId("heat-cell");
    const by = (n: string) => cells.find((c) => c.textContent === n)!;
    expect(by("28").getAttribute("data-value")).toBe("100");
    expect(by("29").getAttribute("data-value")).toBe("none"); // rest
    expect(by("30").getAttribute("data-value")).toBe("0"); // missed
    expect(by("01").getAttribute("data-value")).toBe("none"); // planned, not 0
    expect(by("30")).toHaveAccessibleName("Sep 30: 0%");
    expect(by("29")).toHaveAccessibleName(/no value \(rest day\)/);
    expect(by("01")).toHaveAccessibleName(/no value \(planned\)/);
    expect(screen.getByRole("img", { name: "Weekly completion in percent" })).toBeInTheDocument();
  });

  it("can show nutrition completion instead", async () => {
    serveAll();
    const user = userEvent.setup();
    renderApp("/progress");
    await screen.findAllByTestId("heat-cell");
    await user.click(screen.getByLabelText("Nutrition"));
    const cells = screen.getAllByTestId("heat-cell");
    expect(cells.find((c) => c.textContent === "28")!.getAttribute("data-value")).toBe("90");
    expect(cells.find((c) => c.textContent === "30")!.getAttribute("data-value")).toBe("none");
  });

  it("shows an empty state without days", async () => {
    serveAll({ adherence: { ...adherence(), days: [], weeks: [] } });
    renderApp("/progress");
    expect(await screen.findByText("No data for this month yet.")).toBeInTheDocument();
  });

  it("shows the forbidden state on 403 not_linked", async () => {
    serveAll();
    server.use(http.get(apiUrl(`${A}/adherence`), () => problem(403, "not_linked")));
    renderApp("/progress");
    expect(await screen.findByText("You don't have access to this data.")).toBeInTheDocument();
  });
});

describe("Weekly summary", () => {
  it("shows the tiles with estimated energy and weight start to end", async () => {
    serveAll();
    renderApp("/progress");
    expect(await screen.findByTestId("tile-sessions")).toHaveTextContent("3 of 4");
    expect(screen.getByTestId("tile-completion")).toHaveTextContent("82%");
    const balance = screen.getByTestId("tile-balance");
    expect(balance).toHaveTextContent("estimated");
    expect(balance).toHaveTextContent("-350 kcal");
    expect(balance).toHaveTextContent("Target balance -400 kcal");
    expect(screen.getByTestId("tile-weight")).toHaveTextContent("80 to 79.5 kg");
    expect(screen.getByRole("img", { name: "Daily energy balance" })).toBeInTheDocument();
  });

  it("shows a dash for null averages and converts weights for imperial users", async () => {
    server.use(meOk(meFixture({ units: "imperial" })));
    serveAll({ weekly: weekly({ avg_completion: null, avg_daily_balance_kcal: null, target_daily_balance_kcal: null }) });
    renderApp("/progress");
    expect(await screen.findByTestId("tile-completion")).toHaveTextContent("—");
    expect(screen.getByTestId("tile-completion")).not.toHaveTextContent("0%");
    expect(screen.getByTestId("tile-weight")).toHaveTextContent("176.4 to 175.3 lb");
  });

  it("shows the forbidden state on 403 not_linked", async () => {
    serveAll();
    server.use(http.get(apiUrl(`${A}/weekly-summary`), () => problem(403, "not_linked")));
    renderApp("/progress");
    expect((await screen.findAllByText("You don't have access to this data.")).length).toBeGreaterThan(0);
  });
});

describe("Body", () => {
  it("shows the weight chart and body fat when present", async () => {
    serveAll();
    renderApp("/progress");
    expect(await screen.findByRole("img", { name: "Weight and 7-day average in kg" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Body fat percent" })).toBeInTheDocument();
  });

  it("omits the body fat chart when no point has it", async () => {
    serveAll({ body: body([{ date: "2026-10-26", weight_kg: 79.5, weight_avg_7d_kg: 79.5, body_fat_pct: null }]) });
    renderApp("/progress");
    await screen.findByRole("img", { name: /Weight and 7-day average/ });
    expect(screen.queryByRole("img", { name: "Body fat percent" })).not.toBeInTheDocument();
  });

  it("uses lb for an imperial user and sends the chosen range", async () => {
    server.use(meOk(meFixture({ units: "imperial" })));
    serveAll();
    const seen = serve(`${A}/body`, () => HttpResponse.json(body()));
    const user = userEvent.setup();
    renderApp("/progress");
    expect(await screen.findByRole("img", { name: "Weight and 7-day average in lb" })).toBeInTheDocument();
    const section = screen.getByRole("region", { name: "Body" });
    await user.click(within(section).getByLabelText("52 weeks"));
    await waitFor(() => expect(seen).toContain("52"));
  });

  it("shows an empty state without points", async () => {
    serveAll({ body: body([]) });
    renderApp("/progress");
    expect(await screen.findByText("No weigh-ins in this range yet.")).toBeInTheDocument();
  });

  it("shows the forbidden state on 403 not_linked", async () => {
    serveAll();
    server.use(http.get(apiUrl(`${A}/body`), () => problem(403, "not_linked")));
    renderApp("/progress");
    expect((await screen.findAllByText("You don't have access to this data.")).length).toBeGreaterThan(0);
  });
});

describe("Page access and 360 px layout", () => {
  it("tells a coach that athlete charts come later, without calling the API", async () => {
    server.use(meOk(meFixture({ role: "coach" })));
    renderApp("/progress");
    expect(await screen.findByText(/arrive with the coach dashboard/)).toBeInTheDocument();
  });

  it("keeps every chart and the heat map within a 360 px viewport", async () => {
    vi.stubGlobal("innerWidth", 360);
    serveAll();
    serve(`${A}/exercise/ex-bench`, () => HttpResponse.json(exerciseChart()));
    renderApp("/progress");
    await screen.findAllByTestId("heat-cell");
    await screen.findByRole("img", { name: /Weight and 7-day average/ });
    const charts = screen.getAllByRole("img");
    expect(charts.length).toBeGreaterThanOrEqual(4);
    for (const chart of charts) {
      // Containers shrink (min-w-0) and clip (overflow-hidden); no fixed pixel width wider than the screen.
      expect(chart).toHaveClass("w-full", "min-w-0", "max-w-full", "overflow-hidden");
      for (const el of chart.querySelectorAll("[width]")) {
        const w = Number(el.getAttribute("width"));
        if (!Number.isNaN(w)) expect(w).toBeLessThanOrEqual(360);
      }
    }
    expect(screen.getByRole("article")).toHaveClass("min-w-0");
    expect(screen.getByLabelText("Daily completion this month")).toHaveClass("grid-cols-7");
    vi.unstubAllGlobals();
  });
});
