import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import type { components } from "../src/api/schema";
import { TodayView } from "../src/features/calendar/TodayView";
import { WorkoutScreen } from "../src/features/workout/WorkoutScreen";
import { createQueryClient } from "../src/queryClient";
import { sessionFixture } from "./mocks/calendar";
import { meFixture } from "./mocks/fixtures";
import { apiUrl } from "./mocks/handlers";
import { server } from "./mocks/server";

type Schemas = components["schemas"];

const SQUAT = { id: "ex-squat", name: "Back squat", type: "strength", equipment: "barbell", muscle_group: "quads" } as const;
const CURRENT = { target_weight_kg: 40, reps_min: 8, reps_max: 12, target_seconds: null };
const PROPOSED = { target_weight_kg: 42.5, reps_min: 8, reps_max: 12, target_seconds: null };

function progression(id = "sg-1"): Schemas["Suggestion"] {
  return {
    id,
    athlete_id: meFixture().id,
    kind: "progression",
    status: "pending",
    rule: "double",
    reason: "All 3 sets reached 12 reps at 40 kg → 42.5 kg × 8",
    inputs: {},
    created_at: "2026-10-26T17:48:01Z",
    decided_by: null,
    decided_at: null,
    payload: {
      exercise: SQUAT,
      planned_exercise_id: "pe-squat",
      source_session_id: "s-1",
      current: CURRENT,
      proposed: PROPOSED,
      hint: null,
      applied: null,
    },
  };
}

/** A stateful fake: the list shrinks once a suggestion is decided; decisions are recorded. */
function fakeSuggestions(initial: Schemas["Suggestion"][], decideStatus = 200) {
  let pending = initial;
  const calls: { action: string; id: string; body: unknown }[] = [];
  let listCalls = 0;
  const decide = (action: "accept" | "reject") =>
    http.post(apiUrl(`/suggestions/:id/${action}`), async ({ request, params }) => {
      const text = await request.text();
      calls.push({ action, id: String(params.id), body: text ? JSON.parse(text) : undefined });
      if (decideStatus === 409) {
        pending = [];
        return HttpResponse.json(
          { type: "about:blank", title: "Conflict", status: 409, code: "suggestion_already_decided" },
          { status: 409, headers: { "Content-Type": "application/problem+json" } },
        );
      }
      const decided = pending.find((s) => s.id === params.id)!;
      pending = pending.filter((s) => s.id !== params.id);
      return HttpResponse.json({ ...decided, status: action === "accept" ? "accepted" : "rejected" });
    });
  server.use(
    http.get(apiUrl("/athletes/:athleteId/suggestions"), ({ request }) => {
      // The "recent decisions" list asks for accepted / rejected; only the pending list is counted.
      if (new URL(request.url).searchParams.get("status") !== "pending") {
        return HttpResponse.json({ items: [], weigh_in_hint: null });
      }
      listCalls += 1;
      return HttpResponse.json({ items: pending, weigh_in_hint: null });
    }),
    decide("accept"),
    decide("reject"),
  );
  return { calls, listCalls: () => listCalls };
}

function renderToday(units: "metric" | "imperial" = "metric") {
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <TodayView me={meFixture({ units })} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Suggestions on Today", () => {
  it("lists pending suggestions with old to new targets and the stored reason", async () => {
    fakeSuggestions([progression()]);
    renderToday();
    const card = await screen.findByTestId("suggestion");
    expect(within(card).getByText("Back squat")).toBeInTheDocument();
    expect(within(card).getByText("8-12 reps · 40 kg → 8-12 reps · 42.5 kg")).toBeInTheDocument();
    expect(within(card).getByText(progression().reason)).toBeInTheDocument();
  });

  it("shows nothing when none are pending", async () => {
    fakeSuggestions([]);
    renderToday();
    await screen.findByText("Training");
    await waitFor(() => expect(screen.queryByTestId("suggestion")).not.toBeInTheDocument());
    expect(screen.queryByRole("heading", { name: "Suggestions" })).not.toBeInTheDocument();
  });

  it("accepts without overrides and the suggestion leaves the list", async () => {
    const user = userEvent.setup();
    const fake = fakeSuggestions([progression()]);
    renderToday();
    await user.click(await screen.findByRole("button", { name: "Accept" }));
    await waitFor(() => expect(screen.queryByTestId("suggestion")).not.toBeInTheDocument());
    expect(fake.calls).toEqual([{ action: "accept", id: "sg-1", body: undefined }]);
  });

  it("rejects and the suggestion leaves the list", async () => {
    const user = userEvent.setup();
    const fake = fakeSuggestions([progression()]);
    renderToday();
    await user.click(await screen.findByRole("button", { name: "Reject" }));
    await waitFor(() => expect(screen.queryByTestId("suggestion")).not.toBeInTheDocument());
    expect(fake.calls).toEqual([{ action: "reject", id: "sg-1", body: undefined }]);
  });

  it("edit-then-accept sends overrides in kg, converting from the user's pounds", async () => {
    const user = userEvent.setup();
    const fake = fakeSuggestions([progression()]);
    renderToday("imperial");
    await user.click(await screen.findByRole("button", { name: "Edit" }));
    const weight = screen.getByLabelText("Weight (lb)");
    expect(weight).toHaveValue("93.7");
    await user.clear(weight);
    await user.type(weight, "90");
    const max = screen.getByLabelText("Max reps");
    await user.clear(max);
    await user.type(max, "10");
    await user.click(screen.getByRole("button", { name: "Save and accept" }));
    await waitFor(() => expect(screen.queryByTestId("suggestion")).not.toBeInTheDocument());
    expect(fake.calls).toEqual([
      { action: "accept", id: "sg-1", body: { overrides: { target_weight_kg: 40.8, reps_min: 8, reps_max: 10 } } },
    ]);
  });

  it("rejects invalid edited numbers without calling the API", async () => {
    const user = userEvent.setup();
    const fake = fakeSuggestions([progression()]);
    renderToday();
    await user.click(await screen.findByRole("button", { name: "Edit" }));
    const weight = screen.getByLabelText("Weight (kg)");
    await user.clear(weight);
    await user.type(weight, "abc");
    await user.click(screen.getByRole("button", { name: "Save and accept" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter whole numbers");
    expect(fake.calls).toEqual([]);
  });

  it("explains a 409 suggestion_already_decided and refreshes the list", async () => {
    const user = userEvent.setup();
    const fake = fakeSuggestions([progression()], 409);
    renderToday();
    await user.click(await screen.findByRole("button", { name: "Accept" }));
    await waitFor(() => expect(fake.listCalls()).toBeGreaterThanOrEqual(2));
    await waitFor(() => expect(screen.queryByTestId("suggestion")).not.toBeInTheDocument());
  });

  it("shows the 409 message while the card is still visible", async () => {
    const user = userEvent.setup();
    // The refreshed list still holds the card, so the message stays readable.
    let listCalls = 0;
    server.use(
      http.get(apiUrl("/athletes/:athleteId/suggestions"), () => {
        listCalls += 1;
        return HttpResponse.json({ items: [progression()], weigh_in_hint: null });
      }),
      http.post(apiUrl("/suggestions/:id/accept"), () =>
        HttpResponse.json(
          { type: "about:blank", title: "Conflict", status: 409, code: "suggestion_already_decided" },
          { status: 409, headers: { "Content-Type": "application/problem+json" } },
        ),
      ),
    );
    renderToday();
    await user.click(await screen.findByRole("button", { name: "Accept" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("already decided");
    await waitFor(() => expect(listCalls).toBeGreaterThanOrEqual(2));
  });
});

describe("Pending-suggestion banner", () => {
  const SESSION_ID = "5a1c0a52-0d2e-4f43-8d3b-2f0e8d5a9a01";
  const exercise = (pending: string | null): Schemas["SessionExercise"] => ({
    planned_exercise_id: "pe-squat",
    exercise: SQUAT,
    order: 1,
    is_extra: false,
    rule: "double",
    sets: [],
    reps_min: 6,
    reps_max: 10,
    rest_seconds: 90,
    calibration_hint: null,
    completion: null,
    pending_suggestion_id: pending,
  });

  function renderWorkout(pending: string | null) {
    server.use(
      http.get(apiUrl("/sessions/:id"), () =>
        HttpResponse.json(
          sessionFixture("2026-10-26", { id: SESSION_ID, exercises: [exercise(pending)], editable_until: "2999-01-01T00:00:00Z" }),
        ),
      ),
    );
    const queryClient = createQueryClient();
    queryClient.setDefaultOptions({ queries: { retry: false } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <WorkoutScreen me={meFixture()} sessionId={SESSION_ID} />
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }

  it("is shown when an exercise has a pending suggestion", async () => {
    renderWorkout("sg-1");
    expect(await screen.findByText("Using current targets, suggestion pending.")).toBeInTheDocument();
  });

  it("is not shown when none is pending", async () => {
    renderWorkout(null);
    await screen.findByRole("heading", { name: "Back squat" });
    expect(screen.queryByText(/suggestion pending/)).not.toBeInTheDocument();
  });
});
