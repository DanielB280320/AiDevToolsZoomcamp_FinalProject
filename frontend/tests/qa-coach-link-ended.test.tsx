import { screen } from "@testing-library/react";
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
  training_adherence_7d: 0.85,
  last_log_date: "2026-10-24",
  pending_suggestion_count: 0,
};

// QA (#48): the client list still holds the athlete (cached, or the link ended after it loaded),
// but the athlete's endpoints already answer 403 not_linked. AC: "A coach opening an athlete they
// are not (or no longer) linked to sees a not-linked page (the 403 not_linked is handled, ...)".
describe("QA #48: coach context after the link ended", () => {
  beforeEach(() => server.use(meOk(COACH)));

  it("shows the not-linked page when the athlete's Today answers 403 not_linked", async () => {
    server.use(
      http.get(apiUrl("/coach/athletes"), () => HttpResponse.json({ items: [alice] })),
      http.get(apiUrl("/athletes/:athleteId/days/:date"), () => problem(403, "not_linked")),
      http.get(apiUrl("/athletes/:athleteId/suggestions"), () => problem(403, "not_linked")),
      http.get(apiUrl("/athletes/:athleteId/calendar"), () => problem(403, "not_linked")),
    );
    renderApp(`/coach/clients/${ANA}`);
    expect(await screen.findByTestId("not-linked", {}, { timeout: 3000 })).toBeInTheDocument();
  });
});
