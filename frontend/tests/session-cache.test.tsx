import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "../src/i18n/en.json";
import { meFixture, problem } from "./mocks/fixtures";
import { apiUrl } from "./mocks/handlers";
import { server } from "./mocks/server";
import { renderApp } from "./renderApp";

type User = ReturnType<typeof userEvent.setup>;
type Me = ReturnType<typeof meFixture>;

/**
 * Header state across session changes (src/api/session.ts keeps the `me` cache entry in place).
 * A stateful fake backend: `/me` answers with whoever is signed in, or 401.
 */
function fakeBackend(accounts: Record<string, Me>) {
  const state = { current: null as Me | null, meCalls: 0 };
  server.use(
    http.get(apiUrl("/me"), () => {
      state.meCalls += 1;
      return state.current ? HttpResponse.json(state.current) : problem(401, "not_authenticated");
    }),
    http.post(apiUrl("/auth/login"), async ({ request }) => {
      const { email } = (await request.json()) as { email: string };
      const me = accounts[email];
      if (!me) return problem(401, "invalid_credentials");
      state.current = me;
      return HttpResponse.json(me);
    }),
    http.post(apiUrl("/auth/signup"), async ({ request }) => {
      const body = (await request.json()) as { email: string; display_name: string; timezone: string };
      state.current = meFixture({ email: body.email, display_name: body.display_name, timezone: body.timezone });
      return HttpResponse.json(state.current, { status: 201 });
    }),
    http.post(apiUrl("/auth/logout"), () => {
      state.current = null;
      return new HttpResponse(null, { status: 204 });
    }),
  );
  return state;
}

const signOutButton = () => screen.queryByRole("button", { name: en.nav.signOut });

async function signIn(user: User, email: string) {
  await screen.findByRole("heading", { level: 1, name: en.auth.signIn.title });
  await user.type(screen.getByLabelText(en.auth.fields.email.label), email);
  await user.type(screen.getByLabelText(en.auth.fields.password.label), "a password");
  await user.click(screen.getByRole("button", { name: en.auth.signIn.submit }));
}

describe("session cache and header state", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows sign-out in the header after signing in from a 401 redirect", async () => {
    const backend = fakeBackend({ "ana@example.com": meFixture({ display_name: "Ana" }) });
    const user = userEvent.setup();
    const { router } = renderApp("/today");

    // /me → 401 puts the `me` entry in an error state before the user signs in.
    await screen.findByRole("heading", { level: 1, name: en.auth.signIn.title });
    expect(router.state.location.pathname).toBe("/sign-in");
    expect(signOutButton()).not.toBeInTheDocument();

    await signIn(user, "ana@example.com");

    expect(await screen.findByText("Hi, Ana")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/today");
    expect(signOutButton()).toBeInTheDocument();
    // The sign-in response seeds the cache: /today does not ask for /me again.
    expect(backend.meCalls).toBe(1);
  });

  it("after signing out and in as someone else, shows only the new user", async () => {
    const backend = fakeBackend({
      "ana@example.com": meFixture({ display_name: "Ana" }),
      "ben@example.com": meFixture({ id: "9a1b2c3d-0000-4000-8000-000000000002", display_name: "Ben", role: "coach" }),
    });
    backend.current = meFixture({ display_name: "Ana" });
    const user = userEvent.setup();
    const { router } = renderApp("/today");

    expect(await screen.findByText("Hi, Ana")).toBeInTheDocument();
    await user.click(signOutButton()!);
    await screen.findByRole("heading", { level: 1, name: en.auth.signIn.title });
    await waitFor(() => expect(signOutButton()).not.toBeInTheDocument());

    await signIn(user, "ben@example.com");

    // A coach has no day of their own: Today sends them to the client list (#48).
    expect(await screen.findByRole("heading", { level: 1, name: en.coach.clients.title })).toBeInTheDocument();
    expect(screen.queryByText("Hi, Ana")).not.toBeInTheDocument();
    expect(signOutButton()).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/coach/clients");
  });

  it("shows sign-out after sign-up and today's date in the zone the user chose", async () => {
    // 23:30 UTC Friday is already Saturday in Auckland; the browser zone (jsdom: UTC) must not win.
    vi.useFakeTimers({ toFake: ["Date"], now: new Date("2026-10-23T23:30:00Z") });
    fakeBackend({});
    const user = userEvent.setup();
    const { router } = renderApp("/sign-up");
    const f = en.auth.fields;

    await screen.findByText(en.auth.signUp.title, { selector: "h1" });
    expect(signOutButton()).not.toBeInTheDocument();
    await user.type(screen.getByLabelText(f.email.label), "cleo@example.com");
    await user.type(screen.getByLabelText(f.password.label), "correct-horse");
    await user.type(screen.getByLabelText(f.displayName.label), "Cleo");
    await user.click(screen.getByLabelText(new RegExp(`^${f.role.athlete}`)));
    await user.type(screen.getByLabelText(f.birthDate.label), "1995-04-12");
    await user.selectOptions(screen.getByLabelText(f.timezone.label), "Pacific/Auckland");
    await user.click(screen.getByLabelText(f.disclaimer.label));
    await user.click(screen.getByText(en.auth.signUp.submit, { selector: "button" }));

    expect(await screen.findByText("Hi, Cleo")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/today");
    expect(signOutButton()).toBeInTheDocument();
    const heading = screen.getByRole("heading", { level: 1 });
    expect(heading).toHaveTextContent("Saturday");
    expect(heading.querySelector("time")).toHaveAttribute("datetime", "2026-10-24");
  });
});
