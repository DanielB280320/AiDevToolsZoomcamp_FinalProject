import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { components } from "../src/api/schema";
import en from "../src/i18n/en.json";
import { buildWeighIn } from "../src/features/body/weighIn";
import { meFixture, meOk, problem } from "./mocks/fixtures";
import { apiUrl } from "./mocks/handlers";
import { server } from "./mocks/server";
import { renderApp } from "./renderApp";

type Schemas = components["schemas"];

// 10:00 UTC on 26 Oct 2026: "today" is 2026-10-26 in Madrid.
const NOW = new Date("2026-10-26T10:00:00Z");

const metric = (over: Partial<Schemas["BodyMetric"]> = {}): Schemas["BodyMetric"] => ({
  id: "bm-1",
  date: "2026-10-26",
  weight_kg: 80,
  body_fat_pct: null,
  body_fat_method: null,
  body_fat_explanation: null,
  neck_cm: null,
  waist_cm: null,
  hip_cm: null,
  created_at: "2026-10-26T10:00:00Z",
  ...over,
});

function recalc(id = "rc-1"): Extract<Schemas["Suggestion"], { kind: "recalc" }> {
  return {
    id,
    athlete_id: meFixture().id,
    kind: "recalc",
    status: "pending",
    rule: "weight_change",
    reason: "Weight changed 2.5 % from 80 kg to 82 kg.",
    inputs: {},
    created_at: "2026-10-26T10:00:00Z",
    decided_by: null,
    decided_at: null,
    payload: {
      weight_used_kg: 80,
      new_weight_kg: 82,
      change_pct: 2.5,
      current: { kcal: 2400, protein_g: 160, carbs_g: 260, fat_g: 70 },
      proposed: { kcal: 2450, protein_g: 164, carbs_g: 270, fat_g: 72 },
    },
  };
}

/** A fake body API: one entry per date (a repeat date replaces), records the request bodies. */
function fakeBody(options: { recalc?: ReturnType<typeof recalc> | null } = {}) {
  const store = new Map<string, Schemas["BodyMetric"]>();
  const posts: Schemas["BodyMetricInput"][] = [];
  const decisions: string[] = [];
  let pending: Schemas["Suggestion"][] = [];
  server.use(
    http.get(apiUrl("/athletes/:athleteId/body-metrics"), () =>
      HttpResponse.json({ items: [...store.values()].sort((a, b) => a.date.localeCompare(b.date)) }),
    ),
    http.post(apiUrl("/athletes/:athleteId/body-metrics"), async ({ request }) => {
      const body = (await request.json()) as Schemas["BodyMetricInput"];
      posts.push(body);
      const replaced = store.has(body.date);
      const saved = metric({ id: `bm-${store.size + 1}`, date: body.date, weight_kg: body.weight_kg ?? null, neck_cm: body.neck_cm ?? null });
      store.set(body.date, saved);
      if (options.recalc) pending = [options.recalc];
      return HttpResponse.json({ body_metric: saved, recalc_suggestion: options.recalc ?? null }, { status: replaced ? 200 : 201 });
    }),
    http.get(apiUrl("/athletes/:athleteId/suggestions"), () => HttpResponse.json({ items: pending, weigh_in_hint: null })),
    http.post(apiUrl("/suggestions/:id/:action"), ({ params }) => {
      decisions.push(String(params.action));
      pending = [];
      return HttpResponse.json({ ...options.recalc!, status: params.action === "accept" ? "accepted" : "rejected" });
    }),
  );
  return { posts, decisions };
}

beforeEach(() => {
  // Only Date is faked: MSW and React Query keep real timers.
  vi.useFakeTimers({ toFake: ["Date"], now: NOW });
  server.use(meOk());
});
afterEach(() => vi.useRealTimers());

async function openBody(user = userEvent.setup()) {
  renderApp("/body");
  await screen.findByRole("heading", { name: "Log a weigh-in" });
  return user;
}

describe("buildWeighIn", () => {
  const values = { date: "2026-10-26", weight: "", bodyFat: "", neck: "", waist: "", hip: "" };

  it("converts imperial input to metric", () => {
    const built = buildWeighIn({ ...values, weight: "176.4", waist: "32" }, "imperial", "2026-10-26");
    expect(built).toEqual({ input: { date: "2026-10-26", weight_kg: 80, waist_cm: 81.3 } });
  });

  it("passes metric input through", () => {
    expect(buildWeighIn({ ...values, weight: "80,5", bodyFat: "18" }, "metric", "2026-10-26")).toEqual({
      input: { date: "2026-10-26", weight_kg: 80.5, body_fat_pct: 18 },
    });
  });

  it("rejects a future date, malformed numbers and an empty form", () => {
    expect(buildWeighIn({ ...values, date: "2026-10-27", weight: "80" }, "metric", "2026-10-26")).toEqual({
      errors: { date: { key: "futureDate" } },
    });
    expect(buildWeighIn({ ...values, weight: "8o" }, "metric", "2026-10-26")).toEqual({
      errors: { weight: { key: "invalidNumber" } },
    });
    expect(buildWeighIn(values, "metric", "2026-10-26")).toEqual({ errors: { form: { key: "nothing" } } });
  });
});

describe("Body page: weigh-in form", () => {
  it("sends metric values when the user works in kg/cm and lists the entry", async () => {
    const { posts } = fakeBody();
    const user = await openBody();
    await user.type(screen.getByLabelText(/^Weight/), "80.5");
    await user.type(screen.getByLabelText(/^Neck/), "38");
    await user.click(screen.getByRole("button", { name: "Save weigh-in" }));

    expect(await screen.findByText("Weigh-in saved.")).toBeInTheDocument();
    expect(posts).toEqual([{ date: "2026-10-26", weight_kg: 80.5, neck_cm: 38 }]);
    const row = await screen.findByTestId("weigh-in");
    expect(row).toHaveTextContent("80.5 kg");
  });

  it("shows lb and in to an imperial user while the API receives kg and cm", async () => {
    server.use(meOk(meFixture({ units: "imperial" })));
    const { posts } = fakeBody();
    const user = await openBody();
    await user.type(screen.getByLabelText(/^Weight/), "176.4");
    await user.type(screen.getByLabelText(/^Neck/), "15");
    await user.click(screen.getByRole("button", { name: "Save weigh-in" }));

    await screen.findByText("Weigh-in saved.");
    expect(posts).toEqual([{ date: "2026-10-26", weight_kg: 80, neck_cm: 38.1 }]);
    const row = await screen.findByTestId("weigh-in");
    expect(row).toHaveTextContent("176.4 lb");
    expect(row).toHaveTextContent("Neck 15 in");
  });

  it("confirms a replaced weigh-in and keeps a single row for the date", async () => {
    fakeBody();
    const user = await openBody();
    await user.type(screen.getByLabelText(/^Weight/), "80");
    await user.click(screen.getByRole("button", { name: "Save weigh-in" }));
    await screen.findByText("Weigh-in saved.");

    await user.type(screen.getByLabelText(/^Weight/), "79.4");
    await user.click(screen.getByRole("button", { name: "Save weigh-in" }));

    expect(await screen.findByText(/Replaced the earlier weigh-in for/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("weigh-in")).toHaveTextContent("79.4 kg"));
    expect(screen.getAllByTestId("weigh-in")).toHaveLength(1);
  });

  it("rejects a future date inline without calling the API", async () => {
    const { posts } = fakeBody();
    const user = await openBody();
    const date = screen.getByLabelText("Date");
    await user.clear(date);
    await user.type(date, "2026-10-27");
    await user.type(screen.getByLabelText(/^Weight/), "80");
    await user.click(screen.getByRole("button", { name: "Save weigh-in" }));

    expect(await screen.findByText(en.body.errors.futureDate)).toBeInTheDocument();
    expect(date).toHaveAttribute("aria-invalid", "true");
    expect(posts).toEqual([]);
  });

  it("shows API 422 errors next to their fields", async () => {
    fakeBody();
    server.use(
      http.post(apiUrl("/athletes/:athleteId/body-metrics"), () =>
        problem(422, "validation_error", {
          errors: [{ field: "weight_kg", code: "too_large", message: "Must be at most 300." }],
        }),
      ),
    );
    const user = await openBody();
    await user.type(screen.getByLabelText(/^Weight/), "999");
    await user.click(screen.getByRole("button", { name: "Save weigh-in" }));

    const weight = screen.getByLabelText(/^Weight/);
    expect(await screen.findByText("Must be at most 300.")).toBeInTheDocument();
    expect(weight).toHaveAttribute("aria-invalid", "true");
    expect(weight).toHaveAccessibleDescription("Must be at most 300.");
  });

  it("asks for at least one value", async () => {
    const { posts } = fakeBody();
    const user = await openBody();
    await user.click(screen.getByRole("button", { name: "Save weigh-in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(en.body.errors.nothing);
    expect(posts).toEqual([]);
  });
});

describe("Body page: recalculation prompt", () => {
  async function logWeight(user: ReturnType<typeof userEvent.setup>) {
    await user.type(screen.getByLabelText(/^Weight/), "82");
    await user.click(screen.getByRole("button", { name: "Save weigh-in" }));
  }

  it("shows old vs. new kcal and macros and changes nothing until Accept", async () => {
    const fake = fakeBody({ recalc: recalc() });
    const user = await openBody();
    await logWeight(user);

    const prompt = await screen.findByTestId("recalc-prompt");
    for (const text of ["2400 kcal", "2450 kcal", "160 g", "164 g", "260 g", "270 g", "70 g", "72 g"]) {
      expect(within(prompt).getByText(text)).toBeInTheDocument();
    }
    expect(within(prompt).getByText(/changed by 2.5 %/)).toBeInTheDocument();
    expect(fake.decisions).toEqual([]);
  });

  it("accepts and the prompt closes", async () => {
    const fake = fakeBody({ recalc: recalc() });
    const user = await openBody();
    await logWeight(user);
    await user.click(await screen.findByRole("button", { name: "Accept" }));

    await waitFor(() => expect(screen.queryByTestId("recalc-prompt")).not.toBeInTheDocument());
    expect(fake.decisions).toEqual(["accept"]);
    expect(screen.getByText(en.body.recalc.accepted)).toBeInTheDocument();
  });

  it("rejects and the prompt closes", async () => {
    const fake = fakeBody({ recalc: recalc() });
    const user = await openBody();
    await logWeight(user);
    await user.click(await screen.findByRole("button", { name: "Reject" }));

    await waitFor(() => expect(screen.queryByTestId("recalc-prompt")).not.toBeInTheDocument());
    expect(fake.decisions).toEqual(["reject"]);
    expect(screen.getByText(en.body.recalc.rejected)).toBeInTheDocument();
  });

  it("shows no prompt when the response has no recalc_suggestion", async () => {
    fakeBody();
    const user = await openBody();
    await logWeight(user);
    await screen.findByText("Weigh-in saved.");
    expect(screen.queryByTestId("recalc-prompt")).not.toBeInTheDocument();
  });

  it("offers a still-pending recalculation after a reload", async () => {
    fakeBody({ recalc: recalc() });
    server.use(
      http.get(apiUrl("/athletes/:athleteId/suggestions"), () => HttpResponse.json({ items: [recalc()], weigh_in_hint: null })),
      http.get(apiUrl("/athletes/:athleteId/body-metrics"), () => HttpResponse.json({ items: [metric()] })),
    );
    await openBody();
    expect(await screen.findByTestId("recalc-prompt")).toBeInTheDocument();
  });
});

describe("Body page: coach", () => {
  it("hides the form and the prompt", async () => {
    server.use(meOk(meFixture({ role: "coach" })));
    renderApp("/body");
    expect(await screen.findByText(en.body.coachNotice)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save weigh-in" })).not.toBeInTheDocument();
    expect(screen.queryByTestId("recalc-prompt")).not.toBeInTheDocument();
  });
});
