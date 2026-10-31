import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import type { components } from "../src/api/schema";
import { meFixture, meOk } from "./mocks/fixtures";
import { apiUrl } from "./mocks/handlers";
import { server } from "./mocks/server";
import { renderApp } from "./renderApp";

type Schemas = components["schemas"];

const ANA = "a-1";

describe("plan editor in the coach context", () => {
  it("saves through PUT athletes/{athlete_id}/plan/training with the plan's revision", async () => {
    server.use(
      meOk(meFixture({ id: "c-1", display_name: "Cleo", role: "coach" })),
      http.get(apiUrl("/coach/athletes"), () =>
        HttpResponse.json({
          items: [
            {
              athlete: { id: ANA, display_name: "Alice", role: "athlete" },
              units: "metric",
              timezone: "Europe/Madrid",
              link_id: "l-1",
              linked_since: "2026-10-01T10:00:00Z",
              needs_attention: false,
              attention_reasons: [],
              training_adherence_7d: null,
              last_log_date: null,
              pending_suggestion_count: 0,
            },
          ],
        } satisfies Schemas["CoachAthleteList"]),
      ),
    );
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
    const puts: { path: string; revision: number }[] = [];
    server.use(
      http.get(apiUrl("/athletes/:athleteId/plan"), () => HttpResponse.json(plan)),
      http.put(apiUrl("/athletes/:athleteId/plan/training"), async ({ request }) => {
        const body = (await request.json()) as { revision: number };
        puts.push({ path: new URL(request.url).pathname, revision: body.revision });
        return HttpResponse.json({ ...plan, version: 2, revision: 4, source: "custom" });
      }),
    );
    const user = userEvent.setup();
    renderApp(`/coach/clients/${ANA}/plan`);
    const sets = (await screen.findAllByLabelText("Sets"))[0]!;
    await user.clear(sets);
    await user.type(sets, "4");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(puts).toEqual([{ path: `/api/v1/athletes/${ANA}/plan/training`, revision: 3 }]));
  });
});
