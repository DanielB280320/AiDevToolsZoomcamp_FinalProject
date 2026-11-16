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

const exerciseChart = (weeks = 5, points = [point({}), point({ date: "2026-10-19", top_set_weight_kg: 102.5, is_pr: true })]): Schemas["ExerciseChart"] => ({
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

const kpis = (over: Partial<Schemas["PeriodKpis"]> = {}): Schemas["PeriodKpis"] => ({
  sessions_planned: 4,
  sessions_done: 3,
  sessions_missed: 1,
  avg_training_completion: 0.82,
  avg_nutrition_completion: 0.6,
  active_days: 3,
  volume_kg: 12400,
  personal_records: 2,
  avg_daily_eaten_kcal: 2100,
  avg_daily_burned_exercise_kcal: 350,
  avg_daily_balance_kcal: -350,
  target_daily_balance_kcal: -400,
  weight_avg_start_kg: 80,
  weight_avg_end_kg: 79.5,
  weight_change_kg: -0.5,
  weight_change_per_week_kg: -0.12,
  ...over,
});

const noDeltas = (): Schemas["PeriodDeltas"] => ({
  sessions_planned: null,
  sessions_done: null,
  sessions_missed: null,
  avg_training_completion: null,
  avg_nutrition_completion: null,
  active_days: null,
  volume_kg: null,
  personal_records: null,
  avg_daily_eaten_kcal: null,
  avg_daily_burned_exercise_kcal: null,
  avg_daily_balance_kcal: null,
  target_daily_balance_kcal: null,
  weight_avg_start_kg: null,
  weight_avg_end_kg: null,
  weight_change_kg: null,
  weight_change_per_week_kg: null,
});

const seriesPoint = (start: string, over: Partial<Schemas["PeriodSeriesPoint"]> = {}): Schemas["PeriodSeriesPoint"] => ({
  start,
  sessions_done: 1,
  sessions_planned: 1,
  volume_kg: 4000,
  training_completion: 0.9,
  nutrition_completion: 0.7,
  balance_kcal: -300,
  weight_avg_kg: 80,
  ...over,
});

const periodSummary = (over: Partial<Schemas["PeriodSummary"]> = {}): Schemas["PeriodSummary"] => ({
  from: "2026-09-27",
  to: "2026-10-26",
  days: 30,
  previous_from: "2026-08-28",
  previous_to: "2026-09-26",
  bucket: "day",
  estimated: true,
  current: kpis(),
  previous: kpis({ sessions_done: 2, volume_kg: 10000, avg_training_completion: 0.74, weight_change_kg: -0.2 }),
  deltas: {
    ...noDeltas(),
    sessions_done: 1,
    avg_training_completion: 0.08,
    avg_nutrition_completion: -0.05,
    active_days: 0,
    volume_kg: 2400,
    personal_records: -1,
    avg_daily_balance_kcal: -50,
    avg_daily_eaten_kcal: 120,
    weight_change_kg: -0.3,
  },
  longest_streak_days: 3,
  series: [seriesPoint("2026-10-24"), seriesPoint("2026-10-25", { sessions_done: 0, volume_kg: 0, training_completion: null }), seriesPoint("2026-10-26", { balance_kcal: null })],
  ...over,
});

const body = (points: Schemas["BodyChartPoint"][] = [
  { date: "2026-10-20", weight_kg: 80, weight_avg_7d_kg: 80, body_fat_pct: 18.5 },
  { date: "2026-10-26", weight_kg: 79.5, weight_avg_7d_kg: 79.75, body_fat_pct: null },
]): Schemas["BodyChart"] => ({ weeks: 12, estimated: true, points });

/** Records the `from..to` query of a chart endpoint. */
function serve(path: string, respond: (range: string) => Response | Promise<Response>, seen: string[] = []) {
  server.use(
    http.get(apiUrl(path), ({ request }) => {
      const q = new URL(request.url).searchParams;
      const range = `${q.get("from")}..${q.get("to")}`;
      seen.push(range);
      return respond(range);
    }),
  );
  return seen;
}

function serveAll(over: { adherence?: Schemas["AdherenceChart"]; body?: Schemas["BodyChart"]; period?: Schemas["PeriodSummary"] } = {}) {
  server.use(
    http.get(apiUrl(`${A}/period-summary`), () => HttpResponse.json(over.period ?? periodSummary())),
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

  it("sends the page's selected period and no longer has its own week selector", async () => {
    serveAll();
    const seen = serve(`${A}/exercise/ex-bench`, () => HttpResponse.json(exerciseChart()));
    const user = await pickBench();
    const section = screen.getByRole("region", { name: "Exercise over time" });
    await waitFor(() => expect(seen).toEqual(["2026-09-27..2026-10-26"]));
    expect(within(section).queryByRole("radio")).not.toBeInTheDocument();
    await user.click(screen.getByLabelText("90 days"));
    await waitFor(() => expect(seen).toContain("2026-07-29..2026-10-26"));
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
    expect(await screen.findByText("No finished sessions with this exercise in this period.")).toBeInTheDocument();
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

  it("shows the day's training and nutrition when a day is pointed at or focused (D113)", async () => {
    serveAll();
    const user = userEvent.setup();
    renderApp("/progress");
    const cells = await screen.findAllByTestId("heat-cell");
    const by = (n: string) => cells.find((c) => c.textContent === n)!;
    expect(screen.queryByTestId("heat-detail")).not.toBeInTheDocument();
    await user.hover(by("28"));
    const detail = screen.getByRole("tooltip");
    expect(within(detail).getByText("Monday, September 28")).toBeInTheDocument();
    expect(within(detail).getByText("Training: 100% (done)")).toBeInTheDocument();
    expect(within(detail).getByText("Nutrition: 90%")).toBeInTheDocument();
    expect(by("28")).toHaveAccessibleDescription(/Training: 100% \(done\)/);
    await user.unhover(by("28"));
    expect(screen.queryByTestId("heat-detail")).not.toBeInTheDocument();
    // Keyboard: focus opens it, Escape closes it; a day without values names its status.
    by("29").focus();
    expect(within(await screen.findByRole("tooltip")).getByText("Training: rest day")).toBeInTheDocument();
    expect(within(screen.getByRole("tooltip")).getByText("Nutrition: no value")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByTestId("heat-detail")).not.toBeInTheDocument();
  });

  it("shows a period of up to 31 days as one grid without month buttons (D113)", async () => {
    serveAll();
    renderApp("/progress");
    await screen.findAllByTestId("heat-cell");
    expect(screen.queryByRole("button", { name: "Previous month" })).not.toBeInTheDocument();
    expect(screen.queryByTestId("heat-month")).not.toBeInTheDocument();
  });

  it("pages a longer period by month, opening on the latest one (D113)", async () => {
    // 2026-09-20 .. 2026-11-10: 52 days over three months.
    const days = Array.from({ length: 52 }, (_, i) => day(new Date(Date.UTC(2026, 8, 20 + i)).toISOString().slice(0, 10)));
    serveAll({ adherence: { ...adherence(), from: "2026-09-20", to: "2026-11-10", days } });
    const user = userEvent.setup();
    renderApp("/progress");
    await screen.findAllByTestId("heat-cell");
    const month = screen.getByTestId("heat-month");
    const prev = screen.getByRole("button", { name: "Previous month" });
    const next = screen.getByRole("button", { name: "Next month" });
    expect(month).toHaveTextContent("November 2026");
    expect(screen.getAllByTestId("heat-cell")).toHaveLength(10);
    expect(next).toBeDisabled();
    await user.click(prev);
    expect(month).toHaveTextContent("October 2026");
    expect(screen.getAllByTestId("heat-cell")).toHaveLength(31);
    await user.click(prev);
    expect(month).toHaveTextContent("September 2026");
    expect(screen.getAllByTestId("heat-cell")).toHaveLength(11);
    expect(prev).toBeDisabled();
    await user.click(next);
    expect(month).toHaveTextContent("October 2026");
  });

  it("shows an empty state without days", async () => {
    serveAll({ adherence: { ...adherence(), days: [], weeks: [] } });
    renderApp("/progress");
    expect(await screen.findByText("No data for this period yet.")).toBeInTheDocument();
  });

  it("shows the forbidden state on 403 not_linked", async () => {
    serveAll();
    server.use(http.get(apiUrl(`${A}/adherence`), () => problem(403, "not_linked")));
    renderApp("/progress");
    expect(await screen.findByText("You don't have access to this data.")).toBeInTheDocument();
  });
});

describe("Overview", () => {
  it("shows three rings with period-over-period lines, the previous period named by its length", async () => {
    serveAll();
    renderApp("/progress");
    const sessions = await screen.findByTestId("ring-sessions");
    expect(within(sessions).getByRole("progressbar", { name: "Sessions done" })).toHaveAttribute("aria-valuenow", "75");
    expect(sessions).toHaveTextContent("3 of 4 planned");
    expect(sessions).toHaveTextContent("+1 vs previous 30 days");
    const training = screen.getByTestId("ring-training");
    expect(within(training).getByRole("progressbar", { name: "Training completion" })).toHaveAttribute("aria-valuenow", "82");
    expect(training).toHaveTextContent("+8 pts vs previous 30 days");
    const nutrition = screen.getByTestId("ring-nutrition");
    expect(within(nutrition).getByRole("progressbar", { name: "Nutrition completion" })).toHaveAttribute("aria-valuenow", "60");
    expect(nutrition).toHaveTextContent("-5 pts vs previous 30 days");
  });

  it("shows the KPI tiles with estimated energy, units and deltas", async () => {
    serveAll();
    renderApp("/progress");
    const volume = await screen.findByTestId("kpi-volume");
    expect(volume).toHaveTextContent("12,400 kg");
    expect(volume).toHaveTextContent("+2,400 kg vs previous 30 days");
    expect(screen.getByTestId("kpi-active-days")).toHaveTextContent("No change vs previous 30 days");
    expect(screen.getByTestId("kpi-streak")).toHaveTextContent("3 days");
    expect(screen.getByTestId("kpi-records")).toHaveTextContent("-1 vs previous 30 days");
    const balance = screen.getByTestId("kpi-balance");
    expect(balance).toHaveTextContent("estimated");
    expect(balance).toHaveTextContent("-350 kcal");
    expect(balance).toHaveTextContent("Target balance -400 kcal");
    expect(balance).toHaveTextContent("-50 kcal vs previous 30 days");
    expect(screen.getByTestId("kpi-eaten")).toHaveTextContent("estimated");
    expect(screen.getByTestId("kpi-burned")).toHaveTextContent("estimated");
    const weight = screen.getByTestId("kpi-weight");
    expect(weight).toHaveTextContent("-0.5 kg");
    expect(weight).toHaveTextContent("80 to 79.5 kg");
    expect(weight).toHaveTextContent("-0.1 kg per week");
  });

  it("marks direction with an icon and hidden words, and keeps weight and balance neutral", async () => {
    serveAll();
    renderApp("/progress");
    await screen.findByTestId("kpi-volume");
    const records = within(screen.getByTestId("kpi-records")).getByText(/vs previous/).closest("p")!;
    expect(records).toHaveAttribute("data-direction", "down");
    expect(records).toHaveTextContent("▼");
    expect(records).toHaveTextContent("Down:");
    expect(records).toHaveClass("text-alert");
    const volume = within(screen.getByTestId("kpi-volume")).getByText(/vs previous/).closest("p")!;
    expect(volume).toHaveAttribute("data-direction", "up");
    expect(volume).toHaveClass("text-spruce");
    for (const id of ["kpi-balance", "kpi-weight", "kpi-eaten"]) {
      const line = within(screen.getByTestId(id)).getByText(/vs previous/).closest("p")!;
      expect(line).toHaveClass("text-slate"); // the goal decides, so no good/bad colour
      expect(line.className).not.toMatch(/spruce|alert/);
    }
  });

  it("says there is no data for the previous period and shows dashes without data (empty states)", async () => {
    serveAll({
      period: periodSummary({
        current: kpis({
          sessions_planned: 0,
          sessions_done: 0,
          sessions_missed: 0,
          avg_training_completion: null,
          avg_nutrition_completion: null,
          active_days: 0,
          volume_kg: 0,
          personal_records: 0,
          avg_daily_eaten_kcal: null,
          avg_daily_burned_exercise_kcal: null,
          avg_daily_balance_kcal: null,
          target_daily_balance_kcal: null,
          weight_avg_start_kg: null,
          weight_avg_end_kg: null,
          weight_change_kg: null,
          weight_change_per_week_kg: null,
        }),
        deltas: noDeltas(),
        longest_streak_days: 0,
        series: [],
      }),
    });
    renderApp("/progress");
    const training = await screen.findByTestId("ring-training");
    expect(within(training).getByRole("progressbar")).not.toHaveAttribute("aria-valuenow"); // not 0 %
    expect(training).toHaveTextContent("—");
    expect(training).toHaveTextContent("No data for the previous period");
    expect(training).not.toHaveTextContent("0%");
    for (const id of ["kpi-volume", "kpi-balance", "kpi-eaten", "kpi-burned", "kpi-weight"]) {
      expect(screen.getByTestId(id)).toHaveTextContent("—");
      expect(screen.getByTestId(id)).toHaveTextContent("No data in this period.");
    }
    expect(screen.getByTestId("kpi-streak")).toHaveTextContent("0 days");
    // timelines: one empty message each
    expect(screen.getByText("No finished workouts in this period.")).toBeInTheDocument();
    expect(screen.getByText("No completion figures in this period yet.")).toBeInTheDocument();
    expect(screen.getByText("No days with food logged in this period.")).toBeInTheDocument();
  });

  it("converts volume and weight to lb for an imperial user", async () => {
    server.use(meOk(meFixture({ units: "imperial" })));
    serveAll();
    renderApp("/progress");
    expect(await screen.findByTestId("kpi-volume")).toHaveTextContent("27,337.3 lb");
    expect(screen.getByTestId("kpi-weight")).toHaveTextContent("-1.1 lb");
    expect(screen.getByTestId("kpi-weight")).toHaveTextContent("176.4 to 175.3 lb");
    expect(screen.getByRole("img", { name: /Training volume in lb/ })).toBeInTheDocument();
  });

  it("shows the forbidden state on 403 not_linked", async () => {
    serveAll();
    server.use(http.get(apiUrl(`${A}/period-summary`), () => problem(403, "not_linked")));
    renderApp("/progress");
    expect((await screen.findAllByText("You don't have access to this data.")).length).toBeGreaterThan(0);
  });
});

describe("Timelines", () => {
  it("draws the volume, completion and balance charts with a data table each", async () => {
    serveAll();
    renderApp("/progress");
    expect(await screen.findByRole("img", { name: "Training volume in kg and sessions done per day" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Training and nutrition completion in percent per day" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Average daily energy balance in kcal per day against the target" })).toBeInTheDocument();
    const tables = screen.getAllByRole("table");
    expect(tables).toHaveLength(3);
    expect(within(tables[0]!).getByRole("columnheader", { name: "Volume (kg)" })).toBeInTheDocument();
    expect(within(tables[1]!).getAllByText("90%").length).toBeGreaterThan(0);
    expect(within(tables[2]!).getAllByText("-300 kcal").length).toBeGreaterThan(0);
    expect(screen.getByRole("heading", { name: /Energy balance against target/ })).toHaveTextContent("estimated");
  });

  it("labels weekly buckets by their Monday", async () => {
    serveAll({ period: periodSummary({ bucket: "week", days: 90, series: [seriesPoint("2026-10-19")] }) });
    renderApp("/progress?period=90d");
    expect(await screen.findByRole("img", { name: "Training volume in kg and sessions done per week" })).toBeInTheDocument();
    expect(screen.getAllByRole("cell", { name: "Week of Oct 19" })).toHaveLength(3);
  });
});

describe("Period selector", () => {
  const rangeText = () => screen.getByTestId("period-range").textContent;

  it("offers the five presets and Custom, defaults to 30 days and reloads every section for the choice", async () => {
    serveAll();
    const periods: string[] = [];
    server.use(
      http.get(apiUrl(`${A}/period-summary`), ({ request }) => {
        const q = new URL(request.url).searchParams;
        periods.push(`${q.get("from")}..${q.get("to")}`);
        return HttpResponse.json(periodSummary());
      }),
    );
    const adherenceSeen = serve(`${A}/adherence`, () => HttpResponse.json(adherence()));
    const bodySeen = serve(`${A}/body`, () => HttpResponse.json(body()));
    const user = userEvent.setup();
    const { router } = renderApp("/progress");
    const selector = await screen.findByTestId("period-selector");
    const names = within(selector).getAllByRole("radio").map((r) => (r as HTMLInputElement).value);
    expect(names).toEqual(["7d", "30d", "90d", "6m", "1y", "custom"]);
    expect(within(selector).getByLabelText("30 days")).toBeChecked();
    await waitFor(() => expect(periods).toEqual(["2026-09-27..2026-10-26"]));
    await user.click(within(selector).getByLabelText("7 days"));
    await waitFor(() => expect(periods).toContain("2026-10-20..2026-10-26"));
    await waitFor(() => expect(adherenceSeen).toContain("2026-10-20..2026-10-26"));
    await waitFor(() => expect(bodySeen).toContain("2026-10-20..2026-10-26"));
    expect(router.state.location.search).toBe("?period=7d");
    await user.click(within(selector).getByLabelText("6 months"));
    await waitFor(() => expect(periods).toContain("2026-04-28..2026-10-26")); // 182 days
    await user.click(within(selector).getByLabelText("1 year"));
    await waitFor(() => expect(periods).toContain("2025-10-28..2026-10-26")); // 364 days
  });

  it("keeps the selection in the URL, so a reload shows it", async () => {
    serveAll();
    renderApp("/progress?period=90d");
    expect(await screen.findByLabelText("90 days")).toBeChecked();
    expect(rangeText()).toContain("Jul 29, 2026 to Oct 26, 2026 (90 days)");
  });

  it("restores a custom range from from/to and falls back to 30 days for an invalid URL", async () => {
    serveAll();
    const first = renderApp("/progress?from=2026-10-01&to=2026-10-10");
    expect(await screen.findByLabelText("Custom")).toBeChecked();
    expect(screen.getByLabelText("From")).toHaveValue("2026-10-01");
    expect(screen.getByLabelText("To")).toHaveValue("2026-10-10");
    first.unmount();
    renderApp("/progress?from=2026-10-10&to=2026-10-01");
    expect(await screen.findByLabelText("30 days")).toBeChecked();
  });

  it("steps back and forward by the range length, and disables next when the range ends today", async () => {
    serveAll();
    const user = userEvent.setup();
    const { router } = renderApp("/progress?period=7d");
    const next = await screen.findByRole("button", { name: "Next period" });
    expect(next).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Previous period" }));
    expect(router.state.location.search).toBe("?from=2026-10-13&to=2026-10-19");
    expect(rangeText()).toContain("Oct 13, 2026 to Oct 19, 2026 (7 days)");
    expect(screen.getByLabelText("Custom")).toBeChecked();
    expect(screen.getByRole("button", { name: "Next period" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Next period" }));
    expect(router.state.location.search).toBe("?period=7d"); // back at today: the preset again
    expect(screen.getByRole("button", { name: "Next period" })).toBeDisabled();
  });

  it("validates the custom range inline and keeps the last valid range", async () => {
    serveAll();
    const periods: string[] = [];
    server.use(
      http.get(apiUrl(`${A}/period-summary`), ({ request }) => {
        const q = new URL(request.url).searchParams;
        periods.push(`${q.get("from")}..${q.get("to")}`);
        return HttpResponse.json(periodSummary());
      }),
    );
    const user = userEvent.setup();
    const { router } = renderApp("/progress?from=2026-10-01&to=2026-10-10");
    const from = await screen.findByLabelText("From");
    const to = screen.getByLabelText("To");
    await waitFor(() => expect(periods).toEqual(["2026-10-01..2026-10-10"]));

    await user.clear(to);
    await user.type(to, "2026-09-01"); // before From
    expect(await screen.findByRole("alert")).toHaveTextContent("From must not be after To.");
    await user.clear(to);
    await user.type(to, "2026-10-27"); // tomorrow
    expect(screen.getByRole("alert")).toHaveTextContent("To cannot be after today.");
    await user.clear(from);
    await user.type(from, "2024-01-01");
    await user.clear(to);
    await user.type(to, "2026-10-26");
    expect(screen.getByRole("alert")).toHaveTextContent("The range can cover at most 371 days.");
    expect(router.state.location.search).toBe("?from=2026-10-01&to=2026-10-10"); // last valid range kept
    expect(periods).toEqual(["2026-10-01..2026-10-10"]);

    await user.clear(from);
    await user.type(from, "2026-10-20");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await waitFor(() => expect(router.state.location.search).toBe("?from=2026-10-20&to=2026-10-26"));
    await waitFor(() => expect(periods).toContain("2026-10-20..2026-10-26"));
  });

  it("switches to Custom with the current range", async () => {
    serveAll();
    const user = userEvent.setup();
    const { router } = renderApp("/progress");
    await user.click(await screen.findByLabelText("Custom"));
    expect(router.state.location.search).toBe("?from=2026-09-27&to=2026-10-26");
    expect(screen.getByLabelText("From")).toHaveValue("2026-09-27");
  });
});

describe("Descriptions (F15.6)", () => {
  it("describes the page and every section for the athlete", async () => {
    serveAll();
    renderApp("/progress");
    expect(await screen.findByTestId("progress-description")).toHaveTextContent(/how your training, nutrition, energy balance and body weight moved/);
    expect(screen.getByTestId("progress-description")).toHaveTextContent(/Log your workouts, meals and weigh-ins/);
    for (const key of ["overview", "timelines", "adherence", "exercise", "body"]) {
      expect(screen.getByTestId(`help-${key}`).textContent!.length).toBeGreaterThan(20);
    }
    expect(screen.getByTestId("help-overview")).toHaveTextContent("how fully you followed your training");
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

  it("uses lb for an imperial user and sends the selected period", async () => {
    server.use(meOk(meFixture({ units: "imperial" })));
    serveAll();
    const seen = serve(`${A}/body`, () => HttpResponse.json(body()));
    const user = userEvent.setup();
    renderApp("/progress");
    expect(await screen.findByRole("img", { name: "Weight and 7-day average in lb" })).toBeInTheDocument();
    const section = screen.getByRole("region", { name: "Body" });
    expect(within(section).queryByRole("radio")).not.toBeInTheDocument();
    await waitFor(() => expect(seen).toEqual(["2026-09-27..2026-10-26"]));
    await user.click(screen.getByLabelText("1 year"));
    await waitFor(() => expect(seen).toContain("2025-10-28..2026-10-26"));
  });

  it("shows an empty state without points", async () => {
    serveAll({ body: body([]) });
    renderApp("/progress");
    expect(await screen.findByText("No weigh-ins in this period yet.")).toBeInTheDocument();
  });

  it("shows the forbidden state on 403 not_linked", async () => {
    serveAll();
    server.use(http.get(apiUrl(`${A}/body`), () => problem(403, "not_linked")));
    renderApp("/progress");
    expect((await screen.findAllByText("You don't have access to this data.")).length).toBeGreaterThan(0);
  });
});

describe("Page access and 360 px layout", () => {
  it("tells a coach that charts are on each client's page, without calling the API", async () => {
    server.use(meOk(meFixture({ role: "coach" })));
    renderApp("/progress");
    expect(await screen.findByText(/shown on each client's page/)).toBeInTheDocument();
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
    expect(screen.getByLabelText("Daily completion in the selected period")).toHaveClass("grid-cols-7");
    vi.unstubAllGlobals();
  });
});
