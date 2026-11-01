import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import type { components } from "../src/api/schema";
import en from "../src/i18n/en.json";
import { dayViewFixture, sessionFixture } from "./mocks/calendar";
import { meFixture, meOk } from "./mocks/fixtures";
import { apiUrl } from "./mocks/handlers";
import { server } from "./mocks/server";
import { renderApp } from "./renderApp";

type Schemas = components["schemas"];

const COACH = meFixture({ id: "c-1", display_name: "Cleo", role: "coach" });
const ANA = "a-1";
const BOB = "a-2";

function summary(id: string, name: string, over: Partial<Schemas["CoachAthleteSummary"]> = {}): Schemas["CoachAthleteSummary"] {
  return {
    athlete: { id, display_name: name, role: "athlete" },
    units: "metric",
    timezone: "Europe/Madrid",
    link_id: `l-${id}`,
    linked_since: "2026-10-01T10:00:00Z",
    needs_attention: false,
    attention_reasons: [],
    training_adherence_7d: 0.85,
    last_log_date: "2026-10-24",
    pending_suggestion_count: 0,
    ...over,
  };
}

function serveClients(items: Schemas["CoachAthleteSummary"][]) {
  server.use(http.get(apiUrl("/coach/athletes"), () => HttpResponse.json({ items })));
}

/** Records every API request path so tests can assert nothing used `me`. */
function recordRequests() {
  const seen: string[] = [];
  server.events.on("request:start", ({ request }) => {
    seen.push(`${request.method} ${new URL(request.url).pathname}`);
  });
  return seen;
}

describe("client list", () => {
  beforeEach(() => server.use(meOk(COACH)));

  it("renders the order received, with badges, reasons, adherence and last log", async () => {
    serveClients([
      summary(BOB, "zed", {
        needs_attention: true,
        attention_reasons: ["low_adherence", "inactive"],
        training_adherence_7d: 0.5,
        last_log_date: null,
        pending_suggestion_count: 2,
      }),
      summary(ANA, "Alice", { training_adherence_7d: null }),
    ]);
    renderApp("/coach/clients");

    const rows = await screen.findAllByTestId("client-row");
    // No client-side re-sort: "zed" comes before "Alice" because the API said so.
    expect(rows.map((r) => within(r).getAllByRole("link")[0]!.textContent)).toEqual(["zed", "Alice"]);

    const first = within(rows[0]!);
    expect(first.getByText(en.coach.clients.needsAttention)).toBeInTheDocument();
    expect(first.getAllByTestId("attention-reason").map((e) => e.textContent)).toEqual([
      en.coach.clients.reasons.low_adherence,
      en.coach.clients.reasons.inactive,
    ]);
    expect(first.getByText("50 %")).toBeInTheDocument();
    expect(first.getByText(en.coach.clients.noLogs)).toBeInTheDocument();
    expect(first.getByText("2")).toBeInTheDocument();

    const second = within(rows[1]!);
    expect(second.queryByText(en.coach.clients.needsAttention)).not.toBeInTheDocument();
    expect(second.getByText(en.coach.clients.noAdherence)).toBeInTheDocument();
    expect(second.getByText(/Oct(ober)? 24|24 Oct/)).toBeInTheDocument();
  });

  it("explains how athletes link and points to the coach profile when empty", async () => {
    serveClients([]);
    renderApp("/coach/clients");
    expect(await screen.findByText(en.coach.clients.emptyTitle)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: en.coach.clients.emptyLink })).toHaveAttribute("href", "/coach");
  });

  it("shows an error with retry when the list cannot be loaded", async () => {
    server.use(http.get(apiUrl("/coach/athletes"), () => HttpResponse.json({}, { status: 500 })));
    renderApp("/coach/clients");
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: en.session.retry })).toBeInTheDocument();
  });

  it("opens a client by athlete id", async () => {
    serveClients([summary(ANA, "Alice")]);
    const user = userEvent.setup();
    const { router } = renderApp("/coach/clients");
    await user.click(await screen.findByRole("link", { name: "Alice" }));
    expect(router.state.location.pathname).toBe(`/coach/clients/${ANA}`);
  });

  it("is reachable from the coach navigation", async () => {
    serveClients([]);
    const user = userEvent.setup();
    const { router } = renderApp("/coach");
    await user.click(await screen.findByRole("link", { name: en.coach.nav.clients }));
    expect(router.state.location.pathname).toBe("/coach/clients");
  });
});

describe("client list: athlete", () => {
  it("redirects an athlete to Today", async () => {
    server.use(meOk());
    const { router } = renderApp("/coach/clients");
    await waitFor(() => expect(router.state.location.pathname).toBe("/today"));
  });
});

describe("coach context", () => {
  beforeEach(() => server.use(meOk(COACH)));

  it("shows the banner, the way back, and only requests the athlete's id (never me)", async () => {
    serveClients([summary(ANA, "Alice")]);
    const seen = recordRequests();
    renderApp(`/coach/clients/${ANA}`);

    const banner = await screen.findByRole("region", { name: en.coach.client.bannerLabel });
    expect(within(banner).getByText("Viewing Alice")).toBeInTheDocument();
    expect(within(banner).getByRole("link", { name: en.coach.client.back })).toHaveAttribute("href", "/coach/clients");
    await waitFor(() => expect(seen.some((r) => r.includes(`/athletes/${ANA}/days/today`))).toBe(true));
    expect(seen.filter((r) => r.includes("/athletes/me"))).toEqual([]);
  });

  it("renders no logging controls on Today, even with a session and meals", async () => {
    serveClients([summary(ANA, "Alice")]);
    const planned = {
      id: "pm-1",
      slot: "breakfast",
      order: 0,
      meal: { id: "m-1", name: "Oat bowl", slots: ["breakfast"] },
      portion_factor: 1,
      totals: { kcal: 500, protein_g: 30, carbs_g: 60, fat_g: 10 },
      items: [],
    } as unknown as Schemas["PlannedMeal"];
    server.use(
      http.get(apiUrl("/athletes/:athleteId/days/:date"), () =>
        HttpResponse.json(
          dayViewFixture("2026-10-24", {
            training_status: "planned",
            session: sessionFixture("2026-10-24", { athlete_id: ANA }),
            meals: [{ planned_meal: planned, log: null }],
          }),
        ),
      ),
    );
    renderApp(`/coach/clients/${ANA}`);

    expect(await screen.findByText("Oat bowl")).toBeInTheDocument();
    for (const name of [/start workout/i, /continue workout/i, /done as planned/i, /add set/i, /add food/i, /eaten/i, /^skip$/i, /log weight/i]) {
      expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
      expect(screen.queryByRole("link", { name })).not.toBeInTheDocument();
    }
    expect(screen.getByRole("link", { name: en.coach.client.sessionDetail })).toBeInTheDocument();
  });

  it("offers no weigh-in form on the Body tab", async () => {
    serveClients([summary(ANA, "Alice")]);
    server.use(http.get(apiUrl("/athletes/:athleteId/body-metrics"), () => HttpResponse.json({ items: [] })));
    renderApp(`/coach/clients/${ANA}/body`);
    expect(await screen.findByText(en.body.empty)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /log|save/i })).not.toBeInTheDocument();
  });

  it("lists the pending suggestions and lets the coach accept one", async () => {
    serveClients([summary(ANA, "Alice", { pending_suggestion_count: 1 })]);
    const accepted: string[] = [];
    const suggestion: Schemas["Suggestion"] = {
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
    server.use(
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
    const user = userEvent.setup();
    renderApp(`/coach/clients/${ANA}`);
    await user.click(await screen.findByRole("button", { name: en.suggestions.accept }));
    await waitFor(() => expect(accepted).toEqual(["sg-1"]));
  });

  it("shows a not-linked page, with a way back and no data, for an athlete who is not linked", async () => {
    serveClients([summary(ANA, "Alice")]);
    const seen = recordRequests();
    renderApp(`/coach/clients/${BOB}`);
    expect(await screen.findByTestId("not-linked")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: en.coach.client.back })).toHaveAttribute("href", "/coach/clients");
    expect(seen.filter((r) => r.includes(`/athletes/${BOB}`))).toEqual([]);
  });

  it("redirects an athlete away from a client page", async () => {
    server.use(meOk());
    const { router } = renderApp(`/coach/clients/${ANA}`);
    await waitFor(() => expect(router.state.location.pathname).toBe("/today"));
  });
});

describe("decisions made by the coach", () => {
  it("shows the athlete who decided each suggestion", async () => {
    server.use(meOk());
    const decided = (id: string, status: "accepted" | "rejected", by: Schemas["UserRef"]): Schemas["Suggestion"] =>
      ({
        id,
        athlete_id: meFixture().id,
        kind: "calories",
        status,
        rule: "adaptive_calories",
        reason: "r",
        inputs: {},
        created_at: "2026-10-24T08:00:00Z",
        decided_by: by,
        decided_at: "2026-10-24T09:00:00Z",
        payload: { current_kcal: 2400, proposed_kcal: 2250, delta_kcal: -150, floor_applied: false, applied_kcal: null },
      }) as unknown as Schemas["Suggestion"];
    server.use(
      http.get(apiUrl("/athletes/:athleteId/suggestions"), ({ request }) => {
        const status = new URL(request.url).searchParams.get("status");
        const items =
          status === "accepted"
            ? [decided("sg-1", "accepted", { id: "c-1", display_name: "Cleo", role: "coach" })]
            : status === "rejected"
              ? [decided("sg-2", "rejected", { id: meFixture().id, display_name: "Ana", role: "athlete" })]
              : [];
        return HttpResponse.json({ items, weigh_in_hint: null });
      }),
    );
    renderApp("/today");
    const rows = await screen.findAllByTestId("decided-suggestion");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("Accepted by Cleo (coach)");
    expect(rows[1]).toHaveTextContent(en.suggestions.decided.rejected);
    expect(rows[1]).not.toHaveTextContent("Ana");
  });
});

describe("'edited by' labels", () => {
  const exercise = { id: "ex-1", name: "Bench", type: "strength", equipment: "barbell", muscle_group: "chest" } as const;
  const plan = (editedBy: Schemas["UserRef"] | null): Schemas["Plan"] => ({
    id: "plan-1",
    athlete_id: meFixture().id,
    version: 2,
    source: "custom",
    active: true,
    revision: 2,
    created_by: { id: "c-1", display_name: "Cleo", role: "coach" },
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
        edited_by: editedBy,
        exercises: [
          { id: "pe-1", exercise, order: 0, sets: 3, reps_min: 8, reps_max: 10, target_weight_kg: 50, target_seconds: null, rest_seconds: 90, rule: "double", increment_kg: 2.5, deload_enabled: false, calibration_hint: null },
        ],
      },
    ],
    meal_days: [],
  });

  const servePlan = (editedBy: Schemas["UserRef"] | null) =>
    server.use(meOk(), http.get(apiUrl("/athletes/:athleteId/plan"), () => HttpResponse.json(plan(editedBy))));

  it("shows the coach's name on a day the coach edited, in the athlete's plan editor", async () => {
    servePlan({ id: "c-1", display_name: "Cleo", role: "coach" });
    renderApp("/plan");
    expect(await screen.findByText("Edited by Cleo")).toBeInTheDocument();
  });

  it("shows no label once the athlete edited the day by hand", async () => {
    servePlan({ id: meFixture().id, display_name: "Ana", role: "athlete" });
    renderApp("/plan");
    await screen.findByRole("heading", { name: "Mon: Push" });
    expect(screen.queryByText(/Edited by/)).not.toBeInTheDocument();
  });

  it("shows the coach's name on the athlete's Today view", async () => {
    servePlan({ id: "c-1", display_name: "Cleo", role: "coach" });
    server.use(
      http.get(apiUrl("/athletes/:athleteId/days/:date"), () =>
        HttpResponse.json(dayViewFixture("2026-10-26", { weekday: "mon", training_status: "planned", session: sessionFixture("2026-10-26") })),
      ),
    );
    renderApp("/today");
    expect(await screen.findByText("Edited by Cleo")).toBeInTheDocument();
  });
});
