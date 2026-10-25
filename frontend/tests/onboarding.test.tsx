import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import type { components } from "../src/api/schema";
import en from "../src/i18n/en.json";
import { meFixture, meOk, problem } from "./mocks/fixtures";
import { apiUrl } from "./mocks/handlers";
import { server } from "./mocks/server";
import { renderApp } from "./renderApp";

type Schemas = components["schemas"];
const o = en.onboarding;
const ME = meFixture({ onboarding_completed: false });

const resultFixture = {
  profile: {},
  body_metric: {},
  targets: {
    kcal: 2150,
    protein_g: 140,
    carbs_g: 230,
    fat_g: 70,
    explanation: "Katch-McArdle BMR 1500 kcal x 1.45 lifestyle = 2175 kcal baseline.",
  },
  plan: { training_days: [{}, {}, {}], warnings: ["Home equipment limits some exercises."] },
} as unknown as Schemas["OnboardingResult"];

const next = () => screen.getByRole("button", { name: o.nav.next });
const radio = (label: string) => screen.getByLabelText(new RegExp(`^${label}`));

/** Captures the body the wizard posts and answers with the result. */
function captureOnboarding() {
  const captured: { body?: Schemas["OnboardingRequest"]; athleteId?: string } = {};
  server.use(
    http.post(apiUrl("/athletes/:athleteId/onboarding"), async ({ request, params }) => {
      captured.body = (await request.json()) as Schemas["OnboardingRequest"];
      captured.athleteId = params.athleteId as string;
      return HttpResponse.json(resultFixture, { status: 201 });
    }),
    http.get(apiUrl("/exercises"), ({ request }) => {
      const q = new URL(request.url).searchParams.get("q") ?? "";
      const items = q.toLowerCase().startsWith("squ")
        ? [{ id: "ex-squat", name: "Back squat" }, { id: "ex-front", name: "Front squat" }]
        : [];
      return HttpResponse.json({ items, next_cursor: null });
    }),
  );
  return captured;
}

async function fillBody(user: ReturnType<typeof userEvent.setup>, height: string, weight: string, sex = o.body.sex.female) {
  await user.click(radio(sex));
  await user.type(screen.getByLabelText(/^Height/), height);
  await user.type(screen.getByLabelText(/^Weight/), weight);
  await user.click(next());
}

async function fillRest(user: ReturnType<typeof userEvent.setup>) {
  await user.click(radio(o.lifestyle.active));
  await user.click(next());
  await user.click(radio(o.goal.cutting));
  await user.click(next());
  await user.click(radio(o.training.experience.beginner));
  await user.click(radio(o.training.daysPerWeek.option.replace("{{count}}", "3")));
  for (const day of ["mon", "wed", "fri"] as const) await user.click(screen.getByLabelText(o.training.weekday[day]));
  await user.click(radio(o.training.sessionMinutes.option.replace("{{count}}", "60")));
  await user.click(radio(o.training.equipment.full_gym));
  await user.click(next());
  await user.click(radio(o.diet.diet.omnivore));
  await user.click(screen.getByLabelText(o.diet.allergies.nuts));
  await user.click(radio(o.diet.mealsPerDay.option.replace("{{count}}", "4")));
  await user.click(next());
}

describe("Onboarding wizard", () => {
  it("redirects a new athlete from Today to the wizard", async () => {
    server.use(meOk(ME));
    const { router } = renderApp("/today");
    expect(await screen.findByRole("heading", { name: o.body.title })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/onboarding");
  });

  it("sends an onboarded athlete from the wizard to Today", async () => {
    server.use(meOk(meFixture({ onboarding_completed: true })));
    const { router } = renderApp("/onboarding");
    await waitFor(() => expect(router.state.location.pathname).toBe("/today"));
  });

  it("walks every step in metric, skips body fat, shows targets with explanation, then goes to Today", async () => {
    const captured = captureOnboarding();
    server.use(meOk(ME));
    const user = userEvent.setup();
    const { router } = renderApp("/onboarding");

    await screen.findByRole("heading", { name: o.body.title });
    await fillBody(user, "170", "65");
    await user.click(radio(o.bodyFat.method.skip));
    await user.click(next());
    await fillRest(user);

    // Review step lists the answers in the user's units before anything is sent.
    expect(await screen.findByRole("heading", { name: o.review.title })).toBeInTheDocument();
    expect(screen.getByText("170 cm")).toBeInTheDocument();
    expect(screen.getByText("65 kg")).toBeInTheDocument();
    expect(captured.body).toBeUndefined();

    // After the plan is created the targets and their explanation are shown before leaving.
    server.use(meOk(meFixture({ onboarding_completed: true })));
    await user.click(screen.getByRole("button", { name: o.nav.create }));
    expect(await screen.findByRole("heading", { name: o.result.title })).toBeInTheDocument();
    expect(screen.getByText(resultFixture.targets.explanation)).toBeInTheDocument();
    expect(screen.getByText("2150 kcal")).toBeInTheDocument();
    expect(screen.getByText("140 g")).toBeInTheDocument();
    expect(screen.getByText("Home equipment limits some exercises.")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/onboarding");

    expect(captured.athleteId).toBe(ME.id);
    expect(captured.body).toEqual({
      profile: {
        sex: "female",
        height_cm: 170,
        lifestyle: "active",
        goal: "cutting",
        experience: "beginner",
        days_per_week: 3,
        preferred_days: ["mon", "wed", "fri"],
        session_minutes: 60,
        equipment: "full_gym",
        avoided_exercise_ids: [],
        diet: "omnivore",
        allergies: ["nuts"],
        meals_per_day: 4,
      },
      body_metric: { weight_kg: 65, body_fat_method: "skip" },
    });

    await user.click(screen.getByRole("link", { name: o.nav.goToToday }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/today"));
    expect(await screen.findByText("Hi, Ana")).toBeInTheDocument();
  });

  it("uses feet, inches and pounds for an imperial user and posts metric values (F2.5)", async () => {
    const captured = captureOnboarding();
    server.use(meOk(meFixture({ units: "imperial", onboarding_completed: false })));
    const user = userEvent.setup();
    renderApp("/onboarding");

    await screen.findByRole("heading", { name: o.body.title });
    expect(screen.getByLabelText(/^Height \(feet\)/)).toBeInTheDocument();
    expect(screen.getByLabelText(/^Weight.*lb/)).toBeInTheDocument();
    await user.click(radio(o.body.sex.male));
    await user.type(screen.getByLabelText(/^Height \(feet\)/), "5");
    await user.type(screen.getByLabelText(/^Height \(inches\)/), "10");
    await user.type(screen.getByLabelText(/^Weight/), "154");
    await user.click(next());

    // Navy with tape measures in inches; a male is not asked for hips.
    await user.click(radio(o.bodyFat.method.navy));
    expect(screen.getByLabelText(/^Neck circumference.*in/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/^Hip circumference/)).not.toBeInTheDocument();
    await user.type(screen.getByLabelText(/^Neck circumference/), "15");
    await user.type(screen.getByLabelText(/^Waist circumference/), "34");
    await user.click(next());
    await fillRest(user);

    expect(await screen.findByText("5 ft 10 in")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: o.nav.create }));
    await screen.findByRole("heading", { name: o.result.title });

    expect(captured.body?.profile.height_cm).toBe(177.8);
    expect(captured.body?.body_metric.weight_kg).toBeCloseTo(69.9, 1);
    expect(captured.body?.body_metric).toMatchObject({ body_fat_method: "navy", neck_cm: 38.1, waist_cm: 86.4 });
    expect(captured.body?.body_metric).not.toHaveProperty("hip_cm");
  });

  it("offers a known body-fat percentage and sends it", async () => {
    const captured = captureOnboarding();
    server.use(meOk(ME));
    const user = userEvent.setup();
    renderApp("/onboarding");

    await screen.findByRole("heading", { name: o.body.title });
    await fillBody(user, "180", "80", o.body.sex.male);
    await user.click(radio(o.bodyFat.method.entered));
    await user.type(screen.getByLabelText(/^Body fat/, { selector: "input" }), "18");
    await user.click(next());
    await fillRest(user);
    await user.click(screen.getByRole("button", { name: o.nav.create }));
    await screen.findByRole("heading", { name: o.result.title });

    expect(captured.body?.body_metric).toEqual({ weight_kg: 80, body_fat_method: "entered", body_fat_pct: 18 });
  });

  it("asks a female for hips with the Navy method", async () => {
    server.use(meOk(ME));
    const user = userEvent.setup();
    renderApp("/onboarding");
    await screen.findByRole("heading", { name: o.body.title });
    await fillBody(user, "165", "60");
    await user.click(radio(o.bodyFat.method.navy));
    expect(screen.getByLabelText(/^Hip circumference/)).toBeInTheDocument();
  });

  it("shows range errors in the user's units and stays on the step", async () => {
    server.use(meOk(meFixture({ units: "imperial", onboarding_completed: false })));
    const user = userEvent.setup();
    renderApp("/onboarding");

    await screen.findByRole("heading", { name: o.body.title });
    await user.click(radio(o.body.sex.female));
    await user.type(screen.getByLabelText(/^Height \(feet\)/), "3");
    await user.type(screen.getByLabelText(/^Weight/), "20");
    await user.click(next());

    const height = screen.getByLabelText(/^Height \(feet\)/);
    expect(height).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText(/Height must be between .* ft/)).toBeInTheDocument();
    expect(screen.getByText(/Weight must be between .* lb/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: o.body.title })).toBeInTheDocument();
    expect(height).toHaveFocus();
  });

  it("requires a body-fat choice and a matching number of training days", async () => {
    server.use(meOk(ME));
    const user = userEvent.setup();
    renderApp("/onboarding");
    await screen.findByRole("heading", { name: o.body.title });
    await fillBody(user, "170", "65");

    await user.click(next());
    expect(screen.getByText(o.validation.required)).toBeInTheDocument();
    await user.click(radio(o.bodyFat.method.skip));
    await user.click(next());
    await user.click(radio(o.lifestyle.active));
    await user.click(next());
    await user.click(radio(o.goal.cutting));
    await user.click(next());

    await user.click(radio(o.training.experience.beginner));
    await user.click(radio(o.training.daysPerWeek.option.replace("{{count}}", "4")));
    await user.click(screen.getByLabelText(o.training.weekday.mon));
    await user.click(screen.getByLabelText(o.training.weekday.tue));
    await user.click(radio(o.training.sessionMinutes.option.replace("{{count}}", "45")));
    await user.click(radio(o.training.equipment.bodyweight_only));
    await user.click(next());

    expect(screen.getByText(/pick exactly 4 days\. You picked 2/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: o.training.title })).toBeInTheDocument();
  });

  it("searches the catalog and sends the exercises to avoid", async () => {
    const captured = captureOnboarding();
    server.use(meOk(ME));
    const user = userEvent.setup();
    renderApp("/onboarding");
    await screen.findByRole("heading", { name: o.body.title });
    await fillBody(user, "170", "65");
    await user.click(radio(o.bodyFat.method.skip));
    await user.click(next());
    await user.click(radio(o.lifestyle.active));
    await user.click(next());
    await user.click(radio(o.goal.cutting));
    await user.click(next());
    await user.click(radio(o.training.experience.beginner));
    await user.click(radio(o.training.daysPerWeek.option.replace("{{count}}", "2")));
    await user.click(screen.getByLabelText(o.training.weekday.mon));
    await user.click(screen.getByLabelText(o.training.weekday.thu));
    await user.click(radio(o.training.sessionMinutes.option.replace("{{count}}", "30")));
    await user.click(radio(o.training.equipment.full_gym));

    await user.type(screen.getByLabelText(o.training.avoid.searchLabel), "squ");
    await user.click(await screen.findByRole("button", { name: "Avoid Back squat" }));
    const chosen = screen.getByRole("list", { name: o.training.avoid.selected });
    expect(within(chosen).getByText(/Back squat/)).toBeInTheDocument();
    await user.click(next());
    await user.click(radio(o.diet.diet.vegan));
    await user.click(radio(o.diet.mealsPerDay.option.replace("{{count}}", "3")));
    await user.click(next());
    await user.click(screen.getByRole("button", { name: o.nav.create }));
    await screen.findByRole("heading", { name: o.result.title });

    expect(captured.body?.profile.avoided_exercise_ids).toEqual(["ex-squat"]);
    expect(captured.body?.profile.allergies).toEqual([]);
  });

  it("keeps the answers and shows an error when the server fails, then succeeds on retry", async () => {
    let calls = 0;
    server.use(
      meOk(ME),
      http.post(apiUrl("/athletes/:athleteId/onboarding"), () => {
        calls += 1;
        return calls === 1 ? problem(500, "internal_error") : HttpResponse.json(resultFixture, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderApp("/onboarding");
    await screen.findByRole("heading", { name: o.body.title });
    await fillBody(user, "170", "65");
    await user.click(radio(o.bodyFat.method.skip));
    await user.click(next());
    await fillRest(user);

    await user.click(screen.getByRole("button", { name: o.nav.create }));
    expect(await screen.findByRole("alert")).toHaveTextContent(en.errors.unexpected);
    await user.click(screen.getByRole("button", { name: o.nav.create }));
    expect(await screen.findByRole("heading", { name: o.result.title })).toBeInTheDocument();
  });

  it("explains a 409 already_onboarded", async () => {
    server.use(
      meOk(ME),
      http.post(apiUrl("/athletes/:athleteId/onboarding"), () => problem(409, "already_onboarded")),
    );
    const user = userEvent.setup();
    renderApp("/onboarding");
    await screen.findByRole("heading", { name: o.body.title });
    await fillBody(user, "170", "65");
    await user.click(radio(o.bodyFat.method.skip));
    await user.click(next());
    await fillRest(user);
    await user.click(screen.getByRole("button", { name: o.nav.create }));
    expect(await screen.findByRole("alert")).toHaveTextContent(o.errors.alreadyOnboarded);
  });

  it("lets the user go back and edit from the review step", async () => {
    server.use(meOk(ME));
    const user = userEvent.setup();
    renderApp("/onboarding");
    await screen.findByRole("heading", { name: o.body.title });
    await fillBody(user, "170", "65");
    await user.click(radio(o.bodyFat.method.skip));
    await user.click(next());
    await fillRest(user);

    await user.click(screen.getByRole("button", { name: `Edit ${o.stepNames.goal}` }));
    expect(screen.getByRole("heading", { name: o.goal.title })).toBeInTheDocument();
    expect(radio(o.goal.cutting)).toBeChecked();
  });
});
