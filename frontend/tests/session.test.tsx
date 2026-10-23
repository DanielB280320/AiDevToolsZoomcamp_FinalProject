import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import en from "../src/i18n/en.json";
import { meFixture, meOk, meUnauthenticated, problem } from "./mocks/fixtures";
import { apiUrl } from "./mocks/handlers";
import { server } from "./mocks/server";
import { renderApp } from "./renderApp";

describe("route protection", () => {
  it("redirects /today to sign-in when GET /me answers 401", async () => {
    server.use(meUnauthenticated());

    const { router } = renderApp("/today");

    expect(await screen.findByRole("heading", { level: 1, name: en.auth.signIn.title })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/sign-in");
    expect(screen.queryByRole("button", { name: en.nav.signOut })).not.toBeInTheDocument();
  });

  it("does not request /me more than once on a 401 (no retry loop)", async () => {
    let calls = 0;
    server.use(
      http.get(apiUrl("/me"), () => {
        calls += 1;
        return problem(401, "not_authenticated");
      }),
    );

    renderApp("/today");

    await screen.findByRole("heading", { level: 1, name: en.auth.signIn.title });
    expect(calls).toBe(1);
  });

  it("offers a retry instead of redirecting when /me fails for another reason", async () => {
    server.use(http.get(apiUrl("/me"), () => problem(503, "not_ready")));

    const { router } = renderApp("/today");

    expect(await screen.findByText(en.session.loadFailed)).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/today");

    server.use(meOk(meFixture({ display_name: "Ana" })));
    await userEvent.setup().click(screen.getByRole("button", { name: en.session.retry }));
    expect(await screen.findByText("Hi, Ana")).toBeInTheDocument();
  });
});

describe("sign out", () => {
  it("calls POST /auth/logout and returns to sign-in", async () => {
    let loggedOut = false;
    server.use(
      http.get(apiUrl("/me"), () => (loggedOut ? problem(401, "not_authenticated") : HttpResponse.json(meFixture()))),
      http.post(apiUrl("/auth/logout"), () => {
        loggedOut = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    const { router } = renderApp("/today");

    await user.click(await screen.findByRole("button", { name: en.nav.signOut }));

    expect(await screen.findByRole("heading", { level: 1, name: en.auth.signIn.title })).toBeInTheDocument();
    expect(loggedOut).toBe(true);
    expect(router.state.location.pathname).toBe("/sign-in");
    expect(screen.queryByRole("button", { name: en.nav.signOut })).not.toBeInTheDocument();

    // The cached user is gone: going back to /today asks the API again and is redirected.
    await router.navigate("/today");
    await waitFor(() => expect(router.state.location.pathname).toBe("/sign-in"));
  });

  it("stays signed in and says so when the logout request fails", async () => {
    server.use(
      meOk(),
      http.post(apiUrl("/auth/logout"), () => HttpResponse.error()),
    );
    const user = userEvent.setup();
    const { router } = renderApp("/today");

    await user.click(await screen.findByRole("button", { name: en.nav.signOut }));

    expect(await screen.findByRole("alert")).toHaveTextContent(en.nav.signOutFailed);
    expect(router.state.location.pathname).toBe("/today");
  });
});
