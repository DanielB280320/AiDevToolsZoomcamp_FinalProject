import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import type { components } from "../src/api/schema";
import en from "../src/i18n/en.json";
import { meFixture, meOk } from "./mocks/fixtures";
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
  training_adherence_7d: 0.85,
  last_log_date: "2026-10-24",
  pending_suggestion_count: 1,
};

const suggestion = {
  id: "sg-1",
  athlete_id: ANA,
  kind: "calories",
  status: "pending",
  rule: "adaptive_calories",
  reason: "Weight is flat",
  inputs: {},
  created_at: "2026-10-24T08:00:00Z",
  decided_by: null,
  decided_at: null,
  payload: { current_kcal: 2400, proposed_kcal: 2250, delta_kcal: -150, floor_applied: false, applied_kcal: null },
} as unknown as Schemas["Suggestion"];

// QA (#48) fold-in: a suggestion decision in the coach context invalidates the athlete-targets query
// (the new targets show) and the coach client list (the pending count and attention flags change).
describe("QA #48: a coach's suggestion decision refreshes the targets and the client list", () => {
  beforeEach(() => server.use(meOk(COACH)));

  it("marks athlete-targets invalid and refetches the client list after accept", async () => {
    const accepted: string[] = [];
    let clientListRequests = 0;
    server.events.on("request:start", ({ request }) => {
      if (new URL(request.url).pathname.endsWith("/coach/athletes")) clientListRequests += 1;
    });
    server.use(
      http.get(apiUrl("/coach/athletes"), () => HttpResponse.json({ items: [alice] })),
      http.get(apiUrl("/athletes/:athleteId/suggestions"), ({ request }) =>
        HttpResponse.json({
          items: new URL(request.url).searchParams.get("status") === "pending" && accepted.length === 0 ? [suggestion] : [],
          weigh_in_hint: null,
        }),
      ),
      http.post(apiUrl("/suggestions/:id/accept"), ({ params }) => {
        accepted.push(String(params.id));
        return HttpResponse.json({ ...suggestion, status: "accepted" });
      }),
    );
    const { queryClient } = renderApp(`/coach/clients/${ANA}`);
    // Seed the targets query as if the coach had read them before the decision.
    queryClient.setQueryData(["athlete-targets", ANA], { kcal: 2400 });
    const listRequestsBefore = clientListRequests;
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: en.suggestions.accept }));
    await waitFor(() => expect(accepted).toEqual(["sg-1"]));
    await waitFor(() => expect(queryClient.getQueryState(["athlete-targets", ANA])?.isInvalidated).toBe(true));
    await waitFor(() => expect(clientListRequests).toBeGreaterThan(listRequestsBefore));
  });
});
