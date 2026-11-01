import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import type { components } from "../src/api/schema";
import { meFixture, meOk, problem } from "./mocks/fixtures";
import { apiUrl } from "./mocks/handlers";
import { server } from "./mocks/server";
import { renderApp } from "./renderApp";

type Schemas = components["schemas"];

const COACH = meFixture({ id: "c-1", display_name: "Cleo", role: "coach" });
const ANA = "a-1";

const alice: Schemas["CoachAthleteSummary"] = {
  athlete: { id: ANA, display_name: "Alice", role: "athlete" },
  units: "metric",
  timezone: "Europe/Madrid",
  link_id: "l-a-1",
  linked_since: "2026-10-01T10:00:00Z",
  needs_attention: false,
  attention_reasons: [],
  training_adherence_7d: null,
  last_log_date: null,
  pending_suggestion_count: 0,
};

const exercise = { id: "ex-1", name: "Bench", type: "strength", equipment: "barbell", muscle_group: "chest" } as const;
const plan: Schemas["Plan"] = {
  id: "plan-1",
  athlete_id: ANA,
  version: 1,
  source: "generated",
  active: true,
  revision: 3,
  created_by: { id: ANA, display_name: "Alice", role: "athlete" },
  created_at: "2026-10-20T08:00:00Z",
  updated_at: "2026-10-20T08:00:00Z",
  warnings: [],
  training_days: [
    {
      id: "td-1",
      weekday: "mon",
      name: "Push",
      order: 0,
      estimated_minutes: 40,
      planned_kcal: 200,
      edited_by: null,
      exercises: [
        { id: "pe-1", exercise, order: 0, sets: 3, reps_min: 8, reps_max: 10, target_weight_kg: 50, target_seconds: null, rest_seconds: 90, rule: "double", increment_kg: 2.5, deload_enabled: false, calibration_hint: null },
      ],
    },
  ],
  meal_days: [],
};

// QA (#48): the coach context shell watches every query and mutation of the coach context. A plan
// save that answers 403 not_linked (the link ended while the coach was editing) must turn the page
// into the not-linked page, not leave a silent error, and must not show the athlete's data again.
describe("QA #48: coach plan save after the link ended", () => {
  beforeEach(() => server.use(meOk(COACH)));

  it("shows the not-linked page when a plan save answers 403 not_linked", async () => {
    server.use(
      http.get(apiUrl("/coach/athletes"), () => HttpResponse.json({ items: [alice] })),
      http.get(apiUrl("/athletes/:athleteId/plan"), () => HttpResponse.json(plan)),
      http.put(apiUrl("/athletes/:athleteId/plan/training"), () => problem(403, "not_linked")),
    );
    const user = userEvent.setup();
    renderApp(`/coach/clients/${ANA}/plan`);
    const sets = (await screen.findAllByLabelText("Sets"))[0]!;
    await user.clear(sets);
    await user.type(sets, "4");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByTestId("not-linked", {}, { timeout: 3000 })).toBeInTheDocument();
    expect(screen.queryByLabelText("Sets")).not.toBeInTheDocument();
  });
});
