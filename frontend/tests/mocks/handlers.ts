import { http, HttpResponse } from "msw";

import type { components } from "../../src/api/schema";
import { defaultCalendar, defaultDay } from "./calendar";

type Schemas = components["schemas"];

/** MSW pattern for an API path on any origin, e.g. apiUrl("/healthz") matches http://localhost:3000/api/v1/healthz. */
export const apiUrl = (path: string) => `*/api/v1${path}`;

/** Default handlers: the happy path for every endpoint the shell calls. Responses follow openapi.yaml. */
export const handlers = [
  http.get(apiUrl("/healthz"), () => HttpResponse.json({ status: "ok", version: "test" } satisfies Schemas["Health"])),
  defaultDay(),
  defaultCalendar(),
  http.get(apiUrl("/notifications"), () =>
    HttpResponse.json({ items: [], unread_count: 0, next_cursor: null } satisfies Schemas["NotificationPage"]),
  ),
  http.get(apiUrl("/coach/athletes"), () => HttpResponse.json({ items: [] } satisfies Schemas["CoachAthleteList"])),
  // An empty plan: Today only reads it for the "edited by <coach>" labels (F8.3).
  http.get(apiUrl("/athletes/:athleteId/plan"), ({ params }) =>
    HttpResponse.json({
      id: "plan-default",
      athlete_id: String(params.athleteId),
      version: 1,
      source: "generated",
      active: true,
      revision: 0,
      created_by: { id: String(params.athleteId), display_name: "Ana", role: "athlete" },
      created_at: "2026-10-20T08:00:00Z",
      updated_at: "2026-10-20T08:00:00Z",
      warnings: [],
      training_days: [],
      meal_days: [],
    } satisfies Schemas["Plan"]),
  ),
  http.get(apiUrl("/athletes/:athleteId/suggestions"), () =>
    HttpResponse.json({ items: [], weigh_in_hint: null } satisfies Schemas["SuggestionList"]),
  ),
];
