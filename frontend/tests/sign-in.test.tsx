import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import type { components } from "../src/api/schema";
import en from "../src/i18n/en.json";
import { meFixture, problem } from "./mocks/fixtures";
import { apiUrl } from "./mocks/handlers";
import { server } from "./mocks/server";
import { renderApp } from "./renderApp";

type LogInRequest = components["schemas"]["LogInRequest"];

const field = {
  email: () => screen.getByLabelText(en.auth.fields.email.label),
  password: () => screen.getByLabelText(en.auth.fields.password.label),
};
const submit = () => screen.getByRole("button", { name: en.auth.signIn.submit });

async function fillAndSubmit(user: ReturnType<typeof userEvent.setup>, email = "ana@example.com", password = "secret") {
  await user.type(field.email(), email);
  await user.type(field.password(), password);
  await user.click(submit());
}

describe("sign-in form", () => {
  it("has labelled email and password inputs and a link to sign-up", async () => {
    renderApp("/sign-in");

    expect(await screen.findByRole("heading", { level: 1, name: en.auth.signIn.title })).toBeInTheDocument();
    expect(field.email()).toHaveAttribute("type", "email");
    expect(field.email()).toHaveAttribute("autocomplete", "email");
    expect(field.password()).toHaveAttribute("type", "password");
    expect(field.password()).toHaveAttribute("autocomplete", "current-password");
    expect(screen.getByRole("link", { name: en.auth.signIn.switchLink })).toHaveAttribute("href", "/sign-up");
  });

  it("validates before submitting and focuses the first field with an error", async () => {
    let requests = 0;
    server.use(
      http.post(apiUrl("/auth/login"), () => {
        requests += 1;
        return HttpResponse.json(meFixture());
      }),
    );
    const user = userEvent.setup();
    renderApp("/sign-in");

    await user.click(await screen.findByRole("button", { name: en.auth.signIn.submit }));

    expect(requests).toBe(0);
    expect(field.email()).toHaveAttribute("aria-invalid", "true");
    expect(field.email()).toHaveAccessibleDescription(en.auth.validation.emailRequired);
    expect(field.password()).toHaveAccessibleDescription(en.auth.validation.passwordRequired);
    expect(field.email()).toHaveFocus();

    await user.type(field.email(), "ana@example.com");
    await user.click(submit());
    expect(field.password()).toHaveFocus();
    expect(field.email()).not.toHaveAttribute("aria-invalid");
    expect(requests).toBe(0);
  });

  it("signs in and lands on /today with the user's name", async () => {
    let body: LogInRequest | undefined;
    server.use(
      http.post(apiUrl("/auth/login"), async ({ request }) => {
        body = (await request.json()) as LogInRequest;
        return HttpResponse.json(meFixture({ display_name: "Ana" }));
      }),
    );
    const user = userEvent.setup();
    const { router } = renderApp("/sign-in");

    await screen.findByRole("heading", { level: 1, name: en.auth.signIn.title });
    await fillAndSubmit(user, "  ana@example.com ", "a password");

    expect(await screen.findByText("Hi, Ana")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/today");
    expect(body).toEqual({ email: "ana@example.com", password: "a password" });
    expect(screen.getByRole("button", { name: en.nav.signOut })).toBeInTheDocument();
  });

  it("works with the keyboard only", async () => {
    server.use(http.post(apiUrl("/auth/login"), () => HttpResponse.json(meFixture({ display_name: "Ana" }))));
    const user = userEvent.setup();
    const { router } = renderApp("/sign-in");
    await screen.findByRole("heading", { level: 1, name: en.auth.signIn.title });

    // Tab from the top of the page until the email field has focus, then type and press Enter.
    for (let i = 0; i < 10 && document.activeElement !== field.email(); i += 1) await user.tab();
    expect(field.email()).toHaveFocus();
    await user.keyboard("ana@example.com");
    await user.tab();
    expect(field.password()).toHaveFocus();
    await user.keyboard("a password{Enter}");

    expect(await screen.findByText("Hi, Ana")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/today");
  });

  it("shows one generic message for invalid_credentials and focuses it", async () => {
    server.use(
      http.post(apiUrl("/auth/login"), () =>
        problem(401, "invalid_credentials", { detail: "Email or password is incorrect." }),
      ),
    );
    const user = userEvent.setup();
    const { router } = renderApp("/sign-in");
    await screen.findByRole("heading", { level: 1, name: en.auth.signIn.title });

    await fillAndSubmit(user);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(en.auth.errors.invalidCredentials);
    expect(alert).toHaveFocus();
    // Neither field is blamed: the message must not reveal which one was wrong.
    expect(field.email()).not.toHaveAttribute("aria-invalid");
    expect(field.password()).not.toHaveAttribute("aria-invalid");
    expect(router.state.location.pathname).toBe("/sign-in");
  });

  it.each<[string, Record<string, string>, string]>([
    ["seconds", { "Retry-After": "900" }, "Too many attempts. Try again in 15 minutes."],
    ["an HTTP date", { "Retry-After": new Date(Date.now() + 30_000).toUTCString() }, "Try again in"],
    ["no header", {}, en.auth.errors.rateLimited.later],
  ])("shows a try-again-later message for rate_limited with Retry-After as %s", async (_, headers, text) => {
    server.use(http.post(apiUrl("/auth/login"), () => problem(429, "rate_limited", {}, headers)));
    const user = userEvent.setup();
    renderApp("/sign-in");
    await screen.findByRole("heading", { level: 1, name: en.auth.signIn.title });

    await fillAndSubmit(user);

    expect(await screen.findByRole("alert")).toHaveTextContent(text);
  });

  it("shows API field errors next to the matching field", async () => {
    server.use(
      http.post(apiUrl("/auth/login"), () =>
        problem(422, "validation_error", {
          errors: [{ field: "email", code: "invalid_format", message: "value is not a valid email address" }],
        }),
      ),
    );
    const user = userEvent.setup();
    renderApp("/sign-in");
    await screen.findByRole("heading", { level: 1, name: en.auth.signIn.title });

    await fillAndSubmit(user, "ana@example.c0m");

    await screen.findByText("value is not a valid email address");
    expect(field.email()).toHaveAccessibleDescription("value is not a valid email address");
    expect(field.email()).toHaveFocus();
  });

  it("explains a network failure without leaving the page", async () => {
    server.use(http.post(apiUrl("/auth/login"), () => HttpResponse.error()));
    const user = userEvent.setup();
    renderApp("/sign-in");
    await screen.findByRole("heading", { level: 1, name: en.auth.signIn.title });

    await fillAndSubmit(user);

    expect(await screen.findByRole("alert")).toHaveTextContent(en.errors.network);
  });
});
