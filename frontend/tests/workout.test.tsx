import { QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { components } from "../src/api/schema";
import { WorkoutScreen } from "../src/features/workout/WorkoutScreen";
import type { Clock } from "../src/features/workout/clock";
import { createQueryClient } from "../src/queryClient";
import { dayViewFixture, sessionFixture } from "./mocks/calendar";
import { meFixture, meOk, problem } from "./mocks/fixtures";
import { apiUrl } from "./mocks/handlers";
import { server } from "./mocks/server";
import { renderApp } from "./renderApp";

type Schemas = components["schemas"];

const SESSION_ID = "5a1c0a52-0d2e-4f43-8d3b-2f0e8d5a9a01";
const SQUAT = { id: "ex-squat", name: "Back squat", type: "strength", equipment: "barbell", muscle_group: "quads" } as const;
const PLANK = { id: "ex-plank", name: "Plank", type: "timed", equipment: "bodyweight", muscle_group: "core" } as const;
const PLANNED_SQUAT = "pe-squat";

const sets = (n: number, log: (setNo: number) => Schemas["SetLog"] | null = () => null): Schemas["SessionSet"][] =>
  Array.from({ length: n }, (_, i) => ({
    set_no: i + 1,
    is_extra: false,
    target_reps: 8,
    target_weight_kg: 60,
    target_seconds: null,
    log: log(i + 1),
  }));

function squatExercise(overrides: Partial<Schemas["SessionExercise"]> = {}): Schemas["SessionExercise"] {
  return {
    planned_exercise_id: PLANNED_SQUAT,
    exercise: SQUAT,
    order: 1,
    is_extra: false,
    rule: "double",
    sets: sets(3),
    reps_min: 6,
    reps_max: 10,
    rest_seconds: 90,
    calibration_hint: null,
    completion: null,
    pending_suggestion_id: null,
    ...overrides,
  };
}

function setLog(setNo: number, overrides: Partial<Schemas["SetLog"]> = {}): Schemas["SetLog"] {
  return {
    id: `log-${setNo}`,
    session_id: SESSION_ID,
    planned_exercise_id: PLANNED_SQUAT,
    exercise_id: SQUAT.id,
    set_no: setNo,
    skipped: false,
    target_reps: 8,
    target_weight_kg: 60,
    target_seconds: null,
    reps: 8,
    weight_kg: 60,
    seconds: null,
    distance_m: null,
    logged_at: "2026-10-26T17:00:00Z",
    ...overrides,
  };
}

const sessionOk = (overrides: Partial<Schemas["Session"]> = {}) =>
  http.get(apiUrl("/sessions/:id"), () =>
    HttpResponse.json(
      sessionFixture("2026-10-26", { id: SESSION_ID, exercises: [squatExercise()], editable_until: "2026-10-27T22:59:59Z", ...overrides }),
    ),
  );

/** Records every body posted to the set-logging endpoint. */
function captureSets() {
  const bodies: Schemas["SetLogInput"][] = [];
  server.use(
    http.post(apiUrl("/sessions/:id/sets"), async ({ request }) => {
      const body = (await request.json()) as Schemas["SetLogInput"];
      bodies.push(body);
      return HttpResponse.json(setLog(body.set_no), { status: 201 });
    }),
  );
  return bodies;
}

/** A clock the test moves by hand: no real waiting, no timer leaks. */
function manualClock(start: number) {
  let now = start;
  const callbacks = new Set<() => void>();
  const clock: Clock = {
    now: () => now,
    every: (callback) => {
      callbacks.add(callback);
      return () => callbacks.delete(callback);
    },
  };
  return {
    clock,
    advance(ms: number) {
      act(() => {
        now += ms;
        callbacks.forEach((cb) => cb());
      });
    },
  };
}

const NOW = Date.parse("2026-10-26T17:00:00Z");

function renderScreen(clock: Clock, me = meFixture()) {
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <WorkoutScreen me={me} sessionId={SESSION_ID} clock={clock} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  server.use(meOk(meFixture()));
});
afterEach(() => {
  vi.useRealTimers();
});

describe("Today to first logged set", () => {
  it("logs set 1 as planned in 2 taps from Today", async () => {
    vi.useFakeTimers({ toFake: ["Date"], now: new Date("2026-10-26T11:00:00Z") });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const bodies = captureSets();
    server.use(
      http.get(apiUrl("/athletes/:athleteId/days/:date"), () =>
        HttpResponse.json(
          dayViewFixture("2026-10-26", {
            training_status: "planned",
            session: sessionFixture("2026-10-26", { id: SESSION_ID, exercises: [squatExercise()] }),
          }),
        ),
      ),
      sessionOk(),
    );
    renderApp("/today");

    await user.click(await screen.findByRole("link", { name: "Start workout" }, { timeout: 20_000 })); // tap 1
    await user.click((await screen.findAllByRole("button", { name: /Done as planned/ }))[0]!); // tap 2

    expect(bodies).toEqual([
      { exercise_id: SQUAT.id, planned_exercise_id: PLANNED_SQUAT, set_no: 1, as_planned: true, skipped: false },
    ]);
  });
});

describe("rest timer", () => {
  it("starts with the planned rest after a set and counts down", async () => {
    const { clock, advance } = manualClock(NOW);
    const user = userEvent.setup();
    captureSets();
    server.use(sessionOk({ exercises: [squatExercise({ rest_seconds: 120 })] }));
    renderScreen(clock);

    expect(screen.queryByRole("timer")).not.toBeInTheDocument();
    await user.click((await screen.findAllByRole("button", { name: /Done as planned/ }))[0]!);

    expect(await screen.findByRole("timer")).toHaveTextContent("2:00");
    advance(30_000);
    expect(screen.getByRole("timer")).toHaveTextContent("1:30");
    advance(89_000);
    expect(screen.getByRole("timer")).toHaveTextContent("0:01");
    advance(5_000);
    expect(screen.getByRole("timer")).toHaveTextContent("0:00");
    expect(screen.getByText("Rest over")).toBeInTheDocument();
    expect(screen.getByRole("status", { name: "" })).toHaveTextContent("Rest is over. Ready for Back squat.");
  });

  it("restarts after the next set and can be skipped", async () => {
    const { clock, advance } = manualClock(NOW);
    const user = userEvent.setup();
    captureSets();
    server.use(sessionOk());
    renderScreen(clock);

    const buttons = await screen.findAllByRole("button", { name: /Done as planned/ });
    await user.click(buttons[0]!);
    advance(60_000);
    expect(screen.getByRole("timer")).toHaveTextContent("0:30");
    await user.click(screen.getAllByRole("button", { name: /Done as planned/ })[0]!);
    expect(screen.getByRole("timer")).toHaveTextContent("1:30");

    await user.click(screen.getByRole("button", { name: "Skip rest" }));
    expect(screen.queryByRole("timer")).not.toBeInTheDocument();
  });

  it("does not start after a skipped set", async () => {
    const { clock } = manualClock(NOW);
    const user = userEvent.setup();
    const bodies = captureSets();
    server.use(sessionOk());
    renderScreen(clock);

    await user.click((await screen.findAllByRole("button", { name: /^Skip/ }))[0]!);

    expect(bodies[0]).toMatchObject({ set_no: 1, skipped: true, as_planned: false });
    expect(screen.queryByRole("timer")).not.toBeInTheDocument();
  });
});

describe("editing sets", () => {
  it("sends the entered reps and weight", async () => {
    const { clock } = manualClock(NOW);
    const user = userEvent.setup();
    const bodies = captureSets();
    server.use(sessionOk());
    renderScreen(clock);

    await user.click((await screen.findAllByRole("button", { name: /^Edit/ }))[1]!); // set 2
    const reps = screen.getByLabelText("Reps");
    expect(reps).toHaveValue("8"); // prefilled from the target
    await user.clear(reps);
    await user.type(reps, "6");
    await user.clear(screen.getByLabelText("Weight (kg)"));
    await user.type(screen.getByLabelText("Weight (kg)"), "62,5");
    await user.click(screen.getByRole("button", { name: "Save set" }));

    expect(bodies).toEqual([
      { exercise_id: SQUAT.id, planned_exercise_id: PLANNED_SQUAT, set_no: 2, as_planned: false, skipped: false, reps: 6, weight_kg: 62.5 },
    ]);
  });

  it("converts pounds to kilograms for imperial users", async () => {
    const { clock } = manualClock(NOW);
    const user = userEvent.setup();
    const bodies = captureSets();
    server.use(sessionOk());
    renderScreen(clock, meFixture({ units: "imperial" }));

    await user.click((await screen.findAllByRole("button", { name: /^Edit/ }))[0]!);
    const weight = screen.getByLabelText("Weight (lb)");
    expect(weight).toHaveValue("132.3"); // 60 kg
    await user.clear(weight);
    await user.type(weight, "135");
    await user.click(screen.getByRole("button", { name: "Save set" }));

    expect(bodies[0]?.weight_kg).toBe(61.2);
  });

  it("rejects text that is not a number without calling the API", async () => {
    const { clock } = manualClock(NOW);
    const user = userEvent.setup();
    const bodies = captureSets();
    server.use(sessionOk());
    renderScreen(clock);

    await user.click((await screen.findAllByRole("button", { name: /^Edit/ }))[0]!);
    await user.clear(screen.getByLabelText("Reps"));
    await user.type(screen.getByLabelText("Reps"), "ten");
    await user.click(screen.getByRole("button", { name: "Save set" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Enter a valid number.");
    expect(bodies).toHaveLength(0);
  });

  it("asks for duration on a timed exercise", async () => {
    const { clock } = manualClock(NOW);
    const user = userEvent.setup();
    const bodies = captureSets();
    server.use(
      sessionOk({
        exercises: [
          squatExercise({
            planned_exercise_id: "pe-plank",
            exercise: PLANK,
            sets: [{ set_no: 1, is_extra: false, target_reps: null, target_weight_kg: null, target_seconds: 45, log: null }],
          }),
        ],
      }),
    );
    renderScreen(clock);

    await user.click(await screen.findByRole("button", { name: /^Edit/ }));
    expect(screen.queryByLabelText("Reps")).not.toBeInTheDocument();
    const seconds = screen.getByLabelText("Duration (s)");
    await user.clear(seconds);
    await user.type(seconds, "50");
    await user.click(screen.getByRole("button", { name: "Save set" }));

    expect(bodies[0]).toMatchObject({ exercise_id: PLANK.id, set_no: 1, seconds: 50 });
  });

  it("adds an extra set after the planned ones", async () => {
    const { clock } = manualClock(NOW);
    const user = userEvent.setup();
    const bodies = captureSets();
    server.use(sessionOk());
    renderScreen(clock);

    await user.click(await screen.findByRole("button", { name: /^Add set/ }));
    await user.type(screen.getByLabelText("Reps"), "5");
    await user.type(screen.getByLabelText("Weight (kg)"), "50");
    await user.click(screen.getByRole("button", { name: "Save set" }));

    expect(bodies[0]).toMatchObject({ set_no: 4, reps: 5, weight_kg: 50, planned_exercise_id: PLANNED_SQUAT });
  });

  it("adds an exercise that is not in the plan", async () => {
    const { clock } = manualClock(NOW);
    const user = userEvent.setup();
    const bodies = captureSets();
    server.use(
      sessionOk(),
      http.get(apiUrl("/exercises"), () => HttpResponse.json({ items: [PLANK], next_cursor: null })),
    );
    renderScreen(clock);

    await user.click(await screen.findByRole("button", { name: "Add exercise" }));
    await user.type(screen.getByLabelText("Search exercises by name"), "pla");
    await user.click(await screen.findByRole("button", { name: "Plank" }));
    await user.type(await screen.findByLabelText("Duration (s)"), "40");
    await user.click(screen.getByRole("button", { name: "Save set" }));

    expect(bodies[0]).toEqual({ exercise_id: PLANK.id, planned_exercise_id: null, set_no: 1, as_planned: false, skipped: false, seconds: 40 });
  });

  it("shows the server's reason when a set is refused", async () => {
    const { clock } = manualClock(NOW);
    const user = userEvent.setup();
    server.use(
      sessionOk(),
      http.post(apiUrl("/sessions/:id/sets"), () => problem(409, "edit_window_closed")),
    );
    renderScreen(clock);

    await user.click((await screen.findAllByRole("button", { name: /Done as planned/ }))[0]!);

    expect(await screen.findByRole("alert")).toHaveTextContent("This workout can no longer be edited.");
    expect(screen.queryByRole("timer")).not.toBeInTheDocument();
  });

  it("shows logged sets and hides the controls once the edit window has closed", async () => {
    const { clock } = manualClock(Date.parse("2026-10-28T10:00:00Z"));
    server.use(
      sessionOk({
        status: "done",
        exercises: [squatExercise({ sets: sets(1, (n) => setLog(n)) })],
      }),
    );
    renderScreen(clock);

    expect(await screen.findByText("Logged: 8 reps · 60 kg")).toBeInTheDocument();
    expect(screen.getAllByText("This workout can no longer be edited.").length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: /^Edit/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Finish workout/ })).not.toBeInTheDocument();
  });
});

describe("finish", () => {
  const suggestion = {
    id: "sg-1",
    athlete_id: "a",
    kind: "progression",
    status: "pending",
    rule: "double",
    reason: "All 3 sets reached 12 reps at 40 kg → 42.5 kg × 8",
    inputs: {},
    created_at: "2026-10-26T17:48:01Z",
    decided_by: null,
    decided_at: null,
    payload: {},
  } as unknown as Schemas["Suggestion"];

  const finishOk = (suggestions: Schemas["Suggestion"][]) =>
    http.post(apiUrl("/sessions/:id/finish"), () =>
      HttpResponse.json({
        session: sessionFixture("2026-10-26", {
          id: SESSION_ID,
          status: "done",
          completion: 0.75,
          kcal: 212,
          started_at: "2026-10-26T17:00:00Z",
          finished_at: "2026-10-26T17:48:00Z",
        }),
        suggestions,
      } satisfies Schemas["FinishSessionResult"]),
    );

  it("shows completion, calories, duration and the new suggestions", async () => {
    const { clock } = manualClock(NOW);
    const user = userEvent.setup();
    captureSets();
    server.use(sessionOk(), finishOk([suggestion]));
    renderScreen(clock);

    await user.click((await screen.findAllByRole("button", { name: /Done as planned/ }))[0]!);
    expect(await screen.findByRole("timer")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Finish workout" }));

    const summary = await screen.findByRole("region", { name: "Workout finished" });
    expect(screen.queryByRole("timer")).not.toBeInTheDocument(); // rest ends with the workout
    expect(within(summary).getByText("75%")).toBeInTheDocument();
    expect(within(summary).getByText("212")).toBeInTheDocument();
    expect(within(summary).getByText("48 min")).toBeInTheDocument();
    expect(within(summary).getByText("Calories are estimated.")).toBeInTheDocument();
    expect(within(summary).getByText(suggestion.reason)).toBeInTheDocument();
    expect(within(summary).getByRole("link", { name: "Back to Today" })).toHaveAttribute("href", "/today");
  });

  it("says so when there are no new suggestions, and can go back to the sets", async () => {
    const { clock } = manualClock(NOW);
    const user = userEvent.setup();
    server.use(sessionOk(), finishOk([]));
    renderScreen(clock);

    await user.click(await screen.findByRole("button", { name: "Finish workout" }));
    expect(await screen.findByText("No new suggestions.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Review sets" }));
    expect(screen.getByRole("heading", { name: "Back squat" })).toBeInTheDocument();
  });

  it("shows an error and stays on the sets when finishing fails", async () => {
    const { clock } = manualClock(NOW);
    const user = userEvent.setup();
    server.use(sessionOk(), http.post(apiUrl("/sessions/:id/finish"), () => problem(500, "internal_error")));
    renderScreen(clock);

    await user.click(await screen.findByRole("button", { name: "Finish workout" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("That didn't save. Try again.");
    expect(screen.getByRole("heading", { name: "Back squat" })).toBeInTheDocument();
  });
});

describe("access", () => {
  it("sends a coach back to Today", async () => {
    server.use(meOk(meFixture({ role: "coach" })));
    const { router } = renderApp(`/workout/${SESSION_ID}`);
    await screen.findByText("Your athletes and their latest days will appear here.");
    expect(router.state.location.pathname).toBe("/today");
  });
});
