import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import type { components } from "../src/api/schema";
import { dayViewFixture, sessionFixture } from "./mocks/calendar";
import { meFixture, meOk, problem } from "./mocks/fixtures";
import { apiUrl } from "./mocks/handlers";
import { server } from "./mocks/server";
import { renderApp } from "./renderApp";

type Schemas = components["schemas"];

const COACH = meFixture({ id: "c-1", display_name: "Cleo", role: "coach" });
const ANA = meFixture({ id: "a-1", display_name: "Ana", role: "athlete" });
const SQUAT = { id: "ex-squat", name: "Back squat", type: "strength", equipment: "barbell", muscle_group: "quads" } as const;

const alice: Schemas["CoachAthleteSummary"] = {
  athlete: { id: "a-1", display_name: "Alice", role: "athlete" },
  units: "metric",
  timezone: "Europe/Madrid",
  link_id: "l-1",
  linked_since: "2026-10-01T10:00:00Z",
  needs_attention: false,
  attention_reasons: [],
  training_adherence_7d: 0.85,
  last_log_date: "2026-10-24",
  pending_suggestion_count: 0,
};

function note(id: string, scope: Schemas["NoteScope"], text: string, authorId = "c-1"): Schemas["Note"] {
  return {
    id,
    athlete_id: "a-1",
    author: { id: authorId, display_name: authorId === "c-1" ? "Cleo" : "Dora", role: "coach" },
    scope,
    date: scope === "exercise" ? null : "2026-10-26",
    session_id: scope === "session" ? "s-1" : null,
    exercise: scope === "exercise" ? SQUAT : null,
    text,
    created_at: "2026-10-26T10:00:00Z",
    updated_at: "2026-10-26T10:00:00Z",
  };
}

const NOTES = [
  note("n-day", "day", "Rest well tonight"),
  note("n-session", "session", "Good pace on this workout"),
  note("n-ex", "exercise", "Slow the negative"),
];

function trainingDay(notes: Schemas["Note"][]) {
  const session = sessionFixture("2026-10-26", {
    id: "s-1",
    athlete_id: "a-1",
    status: "planned",
    exercises: [
      {
        planned_exercise_id: "pe-1",
        exercise: SQUAT,
        order: 1,
        is_extra: false,
        rule: "double",
        sets: [{ set_no: 1, is_extra: false, target_reps: 8, target_weight_kg: 60, target_seconds: null, log: null }],
        reps_min: 6,
        reps_max: 10,
        rest_seconds: 90,
        calibration_hint: null,
        completion: null,
        pending_suggestion_id: null,
      },
    ],
  });
  return http.get(apiUrl("/athletes/:athleteId/days/:date"), () =>
    HttpResponse.json(dayViewFixture("2026-10-26", { training_status: "planned", session, notes })),
  );
}

describe("notes: athlete view", () => {
  beforeEach(() => server.use(meOk(ANA), trainingDay(NOTES)));

  it("shows the day, session and exercise notes in context and no create control", async () => {
    renderApp("/today");
    expect(await screen.findByText("Rest well tonight")).toBeInTheDocument();
    const dayThread = screen.getByRole("region", { name: "Coach notes for this day" });
    expect(within(dayThread).getByText("Rest well tonight")).toBeInTheDocument();
    const training = screen.getByRole("region", { name: "Training" });
    expect(within(training).getByText("Good pace on this workout")).toBeInTheDocument();
    const row = within(training).getByText("Back squat").closest("li") as HTMLElement;
    expect(within(row).getByText("Slow the negative")).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /note/i })).not.toBeInTheDocument();
  });

  it("shows the notes next to the exercise in the workout screen", async () => {
    server.use(
      http.get(apiUrl("/sessions/:id"), () =>
        HttpResponse.json(
          sessionFixture("2026-10-26", {
            id: "s-1",
            exercises: [
              {
                planned_exercise_id: "pe-1",
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
                pending_suggestion_id: null,
              },
            ],
          }),
        ),
      ),
    );
    renderApp("/workout/s-1");
    expect(await screen.findByText("Good pace on this workout")).toBeInTheDocument();
    const card = screen.getByRole("heading", { name: "Back squat" }).closest("section") as HTMLElement;
    expect(within(card).getByText("Slow the negative")).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("opens another day with ?date= and requests that day", async () => {
    const asked: string[] = [];
    server.use(
      http.get(apiUrl("/athletes/:athleteId/days/:date"), ({ params }) => {
        asked.push(String(params.date));
        return HttpResponse.json(dayViewFixture(String(params.date), { notes: [NOTES[0]!] }));
      }),
    );
    renderApp("/today?date=2026-10-20");
    expect(await screen.findByText("Rest well tonight")).toBeInTheDocument();
    expect(asked).toContain("2026-10-20");
  });
});

describe("notes: coach view", () => {
  beforeEach(() => {
    server.use(meOk(COACH), http.get(apiUrl("/coach/athletes"), () => HttpResponse.json({ items: [alice] })));
  });

  it("creates a note on the day, the session and an exercise, with no logging controls", async () => {
    const user = userEvent.setup();
    server.use(trainingDay(NOTES));
    const bodies: Schemas["NoteInput"][] = [];
    server.use(
      http.post(apiUrl("/athletes/:athleteId/notes"), async ({ request }) => {
        bodies.push((await request.json()) as Schemas["NoteInput"]);
        return HttpResponse.json(note("new", "day", "x"), { status: 201 });
      }),
    );
    renderApp("/coach/clients/a-1");
    await user.type(await screen.findByLabelText("Add a note: this day", {}, { timeout: 8000 }), "Eat more protein");
    await user.click(screen.getAllByRole("button", { name: "Save note" })[2]!); // the day thread is last
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toEqual({ scope: "day", date: "2026-10-26", text: "Eat more protein" });

    await user.type(screen.getByLabelText("Add a note: this workout"), "Nice work");
    await user.click(screen.getAllByRole("button", { name: "Save note" })[0]!); // session thread comes first
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies[1]).toEqual({ scope: "session", session_id: "s-1", text: "Nice work" });

    await user.type(screen.getByLabelText("Add a note: Back squat"), "Brace harder");
    await user.click(screen.getAllByRole("button", { name: "Save note" })[1]!); // then the exercise
    await waitFor(() => expect(bodies).toHaveLength(3));
    expect(bodies[2]).toEqual({ scope: "exercise", exercise_id: "ex-squat", session_id: "s-1", text: "Brace harder" });
    expect(screen.queryByRole("button", { name: /start workout|done as planned|log/i })).not.toBeInTheDocument();
  });

  it("lets the author edit and delete their note but not another coach's", async () => {
    const user = userEvent.setup();
    server.use(trainingDay([note("mine", "day", "My note"), note("theirs", "session", "Their note", "c-2")]));
    const puts: { id: string; body: unknown }[] = [];
    const deletes: string[] = [];
    server.use(
      http.put(apiUrl("/athletes/:athleteId/notes/:noteId"), async ({ params, request }) => {
        puts.push({ id: String(params.noteId), body: await request.json() });
        return HttpResponse.json(note("mine", "day", "Edited"));
      }),
      http.delete(apiUrl("/athletes/:athleteId/notes/:noteId"), ({ params }) => {
        deletes.push(String(params.noteId));
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderApp("/coach/clients/a-1");
    await screen.findByText("My note", {}, { timeout: 8000 });
    expect(screen.getAllByRole("button", { name: "Edit note" })).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: "Delete note" })).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: "Edit note" }));
    const box = screen.getByLabelText("Edit your note");
    await user.clear(box);
    await user.type(box, "Edited");
    await user.click(within(box.closest("form") as HTMLElement).getByRole("button", { name: "Save note" }));
    await waitFor(() => expect(puts).toEqual([{ id: "mine", body: { text: "Edited" } }]));
    await user.click(await screen.findByRole("button", { name: "Delete note" }, { timeout: 8000 }));
    await waitFor(() => expect(deletes).toEqual(["mine"]));
  });
});

describe("coach shell after a re-link (#48 QA)", () => {
  it("shows the client again without leaving the page once the active links include it", async () => {
    const user = userEvent.setup();
    let linked = false;
    server.use(
      meOk(COACH),
      http.get(apiUrl("/coach/athletes"), () => HttpResponse.json({ items: linked ? [alice] : [] })),
    );
    const { router } = renderApp("/coach/clients/a-1");
    expect(await screen.findByTestId("not-linked")).toBeInTheDocument();
    linked = true; // the athlete re-linked in the meantime
    await user.click(screen.getByRole("button", { name: "Check again" }));
    expect(await screen.findByRole("region", { name: "Athlete you are viewing" })).toBeInTheDocument();
    expect(screen.queryByTestId("not-linked")).not.toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/coach/clients/a-1");
  });

  it("recovers after a 403 not_linked on a loaded client once the list holds it under a new link", async () => {
    const user = userEvent.setup();
    let ended = true;
    server.use(
      meOk(COACH),
      http.get(apiUrl("/coach/athletes"), () => HttpResponse.json({ items: [{ ...alice, link_id: ended ? "l-1" : "l-2" }] })),
      http.get(apiUrl("/athletes/:athleteId/days/:date"), ({ params }) =>
        ended ? problem(403, "not_linked") : HttpResponse.json(dayViewFixture(String(params.date))),
      ),
    );
    renderApp("/coach/clients/a-1");
    // The list still holds the client, but its data answers 403: the page shows not-linked.
    expect(await screen.findByTestId("not-linked")).toBeInTheDocument();
    // Checking again while the list still shows the old link keeps the page (no flicker loop).
    await user.click(screen.getByRole("button", { name: "Check again" }));
    expect(await screen.findByTestId("not-linked")).toBeInTheDocument();
    ended = false; // re-linked: a new link id, and the data answers again
    await user.click(screen.getByRole("button", { name: "Check again" }));
    expect(await screen.findByRole("region", { name: "Athlete you are viewing" }, { timeout: 5000 })).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByTestId("not-linked")).not.toBeInTheDocument());
  });

  it("a client that stays unlinked keeps the page and requests no athlete data", async () => {
    const user = userEvent.setup();
    const seen: string[] = [];
    server.events.on("request:start", ({ request }) => seen.push(new URL(request.url).pathname));
    server.use(meOk(COACH), http.get(apiUrl("/coach/athletes"), () => HttpResponse.json({ items: [] })));
    renderApp("/coach/clients/a-1");
    await screen.findByTestId("not-linked");
    await user.click(screen.getByRole("button", { name: "Check again" }));
    await waitFor(() => expect(seen.filter((p) => p.endsWith("/coach/athletes")).length).toBeGreaterThan(1));
    expect(screen.getByTestId("not-linked")).toBeInTheDocument();
    expect(seen.filter((p) => p.includes("/athletes/a-1/"))).toEqual([]);
  });
});
