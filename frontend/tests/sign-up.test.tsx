import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import type { components } from "../src/api/schema";
import en from "../src/i18n/en.json";
import { meFixture, problem } from "./mocks/fixtures";
import { apiUrl } from "./mocks/handlers";
import { server } from "./mocks/server";
import { renderApp } from "./renderApp";

type SignUpRequest = components["schemas"]["SignUpRequest"];
type User = ReturnType<typeof userEvent.setup>;

const f = en.auth.fields;
const field = {
  email: () => screen.getByLabelText(f.email.label),
  password: () => screen.getByLabelText(f.password.label),
  displayName: () => screen.getByLabelText(f.displayName.label),
  athlete: () => screen.getByLabelText(new RegExp(`^${f.role.athlete}`)),
  coach: () => screen.getByLabelText(new RegExp(`^${f.role.coach}`)),
  birthDate: () => screen.getByLabelText(f.birthDate.label),
  metric: () => screen.getByLabelText(new RegExp(`^${f.units.metric}`)),
  imperial: () => screen.getByLabelText(new RegExp(`^${f.units.imperial}`)),
  timezone: () => screen.getByLabelText(f.timezone.label),
  disclaimer: () => screen.getByLabelText(f.disclaimer.label),
};
// Text/label queries, not *ByRole: role queries walk the ~400 time-zone options on every call.
const submit = () => screen.getByText(en.auth.signUp.submit, { selector: "button" });

async function openSignUp() {
  const view = renderApp("/sign-up");
  await screen.findByText(en.auth.signUp.title, { selector: "h1" });
  return view;
}

async function fillValid(user: User, overrides: { password?: string; birthDate?: string } = {}) {
  await user.type(field.email(), "ana@example.com");
  await user.type(field.password(), overrides.password ?? "correct-horse");
  await user.type(field.displayName(), "Ana");
  await user.click(field.athlete());
  await user.type(field.birthDate(), overrides.birthDate ?? "1995-04-12");
  await user.click(field.disclaimer());
}

function captureSignUp(response: () => Response = () => HttpResponse.json(meFixture(), { status: 201 })) {
  const bodies: SignUpRequest[] = [];
  server.use(
    http.post(apiUrl("/auth/signup"), async ({ request }) => {
      bodies.push((await request.json()) as SignUpRequest);
      return response();
    }),
  );
  return bodies;
}

describe("sign-up form fields", () => {
  it("has every SignUpRequest field, labelled", async () => {
    await openSignUp();

    expect(field.email()).toHaveAttribute("type", "email");
    expect(field.password()).toHaveAttribute("type", "password");
    expect(field.password()).toHaveAttribute("autocomplete", "new-password");
    expect(field.password()).toHaveAccessibleDescription(f.password.newHint);
    expect(field.displayName()).toHaveAttribute("type", "text");
    expect(field.athlete()).toHaveAttribute("type", "radio");
    expect(field.coach()).toHaveAttribute("type", "radio");
    expect(field.athlete()).toHaveAttribute("name", "role");
    expect(field.coach()).toHaveAttribute("name", "role");
    expect(field.athlete().closest("fieldset")).toHaveAccessibleName(f.role.legend);
    expect(field.birthDate()).toHaveAttribute("type", "date");
    expect(field.metric()).toHaveAttribute("name", "units");
    expect(field.imperial()).toHaveAttribute("name", "units");
    expect(field.metric().closest("fieldset")).toHaveAccessibleName(f.units.legend);
    expect(field.timezone().tagName).toBe("SELECT");
    expect(field.disclaimer()).toHaveAttribute("type", "checkbox");
    expect(field.disclaimer()).not.toBeChecked();
    expect(screen.getByText(en.auth.signUp.switchLink, { selector: "a" })).toHaveAttribute("href", "/sign-in");
  });

  it("shows the §6.3 disclaimer text with the checkbox and reads it out with it", async () => {
    await openSignUp();

    const form = field.email().closest("form")!;
    expect(form).toHaveAccessibleName(en.auth.signUp.title);
    expect(form).toHaveTextContent(en.footer.disclaimer);
    expect(field.disclaimer()).toHaveAccessibleDescription(en.footer.disclaimer);
  });

  it("pre-fills the time zone from the browser", async () => {
    const real = Intl.DateTimeFormat.prototype.resolvedOptions;
    vi.spyOn(Intl.DateTimeFormat.prototype, "resolvedOptions").mockImplementation(function (this: Intl.DateTimeFormat) {
      return { ...real.call(this), timeZone: "Asia/Tokyo" };
    });

    await openSignUp();

    expect(field.timezone()).toHaveValue("Asia/Tokyo");
    expect(within(field.timezone()).getByText("Europe/Madrid", { selector: "option" })).toBeInTheDocument();
  });

  it("starts with no role chosen and metric units", async () => {
    await openSignUp();

    expect(field.athlete()).not.toBeChecked();
    expect(field.coach()).not.toBeChecked();
    expect(field.metric()).toBeChecked();
  });
});

describe("sign-up client-side validation", () => {
  it("blocks submit with every required field missing and focuses the first one", async () => {
    const bodies = captureSignUp();
    const user = userEvent.setup();
    await openSignUp();

    await user.click(submit());

    expect(bodies).toHaveLength(0);
    expect(field.email()).toHaveFocus();
    expect(field.email()).toHaveAccessibleDescription(en.auth.validation.emailRequired);
    expect(field.password()).toHaveAccessibleDescription(`${f.password.newHint} ${en.auth.validation.passwordRequired}`);
    expect(field.displayName()).toHaveAccessibleDescription(`${f.displayName.hint} ${en.auth.validation.displayNameRequired}`);
    expect(field.athlete().closest("fieldset")).toHaveAccessibleDescription(`${f.role.hint} ${en.auth.validation.roleRequired}`);
    expect(field.birthDate()).toHaveAccessibleDescription(`${f.birthDate.hint} ${en.auth.validation.birthDateRequired}`);
    expect(field.disclaimer()).toHaveAccessibleDescription(`${en.footer.disclaimer} ${en.auth.validation.disclaimerRequired}`);
  });

  it("requires a password of at least 10 characters", async () => {
    const bodies = captureSignUp();
    const user = userEvent.setup();
    await openSignUp();

    await fillValid(user, { password: "123456789" });
    await user.click(submit());

    expect(bodies).toHaveLength(0);
    expect(await screen.findByText("Use at least 10 characters.")).toBeInTheDocument();
    expect(field.password()).toHaveFocus();
  });

  it("requires the disclaimer to be checked", async () => {
    const bodies = captureSignUp();
    const user = userEvent.setup();
    await openSignUp();

    await fillValid(user);
    await user.click(field.disclaimer()); // uncheck
    await user.click(submit());

    expect(bodies).toHaveLength(0);
    expect(screen.getByText(en.auth.validation.disclaimerRequired)).toBeInTheDocument();
    expect(field.disclaimer()).toHaveFocus();
  });

  it("focuses the first role option when the role is the first error", async () => {
    captureSignUp();
    const user = userEvent.setup();
    await openSignUp();

    await user.type(field.email(), "ana@example.com");
    await user.type(field.password(), "correct-horse");
    await user.type(field.displayName(), "Ana");
    await user.click(submit());

    expect(field.athlete()).toHaveFocus();
  });
});

describe("sign-up submit", () => {
  it("sends the SignUpRequest and lands on /today with the display name", async () => {
    const bodies = captureSignUp(() => HttpResponse.json(meFixture({ display_name: "Ana" }), { status: 201 }));
    const user = userEvent.setup();
    const { router } = await openSignUp();

    await fillValid(user);
    await user.click(field.imperial());
    await user.selectOptions(field.timezone(), "Europe/Madrid");
    await user.click(submit());

    expect(await screen.findByText("Hi, Ana")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/today");
    expect(bodies).toEqual([
      {
        email: "ana@example.com",
        password: "correct-horse",
        display_name: "Ana",
        role: "athlete",
        birth_date: "1995-04-12",
        units: "imperial",
        timezone: "Europe/Madrid",
        accept_disclaimer: true,
      },
    ]);
  });

  it("can be completed with the keyboard only", async () => {
    const bodies = captureSignUp(() => HttpResponse.json(meFixture({ display_name: "Kim", role: "coach" }), { status: 201 }));
    const user = userEvent.setup();
    const { router } = await openSignUp();

    for (let i = 0; i < 10 && document.activeElement !== field.email(); i += 1) await user.tab();
    expect(field.email()).toHaveFocus();
    await user.keyboard("kim@example.com");
    await user.tab();
    await user.keyboard("correct-horse");
    await user.tab();
    await user.keyboard("Kim");
    await user.tab();
    expect(field.athlete()).toHaveFocus();
    await user.keyboard("{ArrowRight}");
    expect(field.coach()).toBeChecked();
    await user.tab();
    expect(field.birthDate()).toHaveFocus();
    await user.keyboard("1990-02-03");
    await user.tab();
    expect(field.metric()).toHaveFocus();
    await user.tab();
    expect(field.timezone()).toHaveFocus();
    await user.tab();
    expect(field.disclaimer()).toHaveFocus();
    await user.keyboard(" ");
    expect(field.disclaimer()).toBeChecked();
    await user.tab();
    expect(submit()).toHaveFocus();
    await user.keyboard("{Enter}");

    // A coach lands on the client list (Today redirects there).
    expect(await screen.findByRole("heading", { level: 1, name: "Clients" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/coach/clients");
    expect(bodies[0]).toMatchObject({ email: "kim@example.com", role: "coach", birth_date: "1990-02-03", units: "metric" });
  });
});

describe("sign-up API errors", () => {
  it.each<[string, () => Response, () => HTMLElement, string]>([
    [
      "underage",
      () =>
        problem(422, "underage", {
          errors: [{ field: "birth_date", code: "underage", message: "You must be 18 or older." }],
        }),
      () => field.birthDate(),
      en.auth.errors.underage,
    ],
    ["disclaimer_required", () => problem(422, "disclaimer_required"), () => field.disclaimer(), en.auth.validation.disclaimerRequired],
    ["email_taken", () => problem(409, "email_taken", { detail: "Email already registered." }), () => field.email(), en.auth.errors.emailTaken],
  ])("shows the i18n message for %s next to its field and focuses it", async (_, response, target, message) => {
    captureSignUp(response);
    const user = userEvent.setup();
    const { router } = await openSignUp();

    await fillValid(user);
    await user.click(submit());

    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(target()).toHaveAttribute("aria-invalid", "true");
    expect(target()).toHaveFocus();
    expect(router.state.location.pathname).toBe("/sign-up");
  });

  it("shows API errors[].field messages next to the matching fields", async () => {
    captureSignUp(() =>
      problem(422, "validation_error", {
        errors: [
          { field: "display_name", code: "too_long", message: "String should have at most 60 characters" },
          { field: "timezone", code: "invalid_choice", message: "Unknown time zone." },
        ],
      }),
    );
    const user = userEvent.setup();
    await openSignUp();

    await fillValid(user);
    await user.click(submit());

    await screen.findByText("Unknown time zone.");
    expect(field.displayName()).toHaveAccessibleDescription(`${f.displayName.hint} String should have at most 60 characters`);
    expect(field.timezone()).toHaveAccessibleDescription(`${f.timezone.hint} Unknown time zone.`);
    expect(field.displayName()).toHaveFocus();
    expect(document.querySelector("[role=alert]")).toBeNull();
  });

  it("shows a rate-limit message using Retry-After", async () => {
    captureSignUp(() => problem(429, "rate_limited", {}, { "Retry-After": "120" }));
    const user = userEvent.setup();
    await openSignUp();

    await fillValid(user);
    await user.click(submit());

    const alert = await screen.findByText(/./, { selector: "[role=alert]" });
    expect(alert).toHaveTextContent("Too many attempts. Try again in 2 minutes.");
    expect(alert).toHaveFocus();
  });

  it("shows the server error message on a 500", async () => {
    captureSignUp(() => problem(500, "internal_error"));
    const user = userEvent.setup();
    await openSignUp();

    await fillValid(user);
    await user.click(submit());

    expect(await screen.findByText(/./, { selector: "[role=alert]" })).toHaveTextContent(en.errors.unexpected);
  });
});
