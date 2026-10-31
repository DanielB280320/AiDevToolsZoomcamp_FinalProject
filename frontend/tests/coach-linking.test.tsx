import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import type { components } from "../src/api/schema";
import en from "../src/i18n/en.json";
import { meFixture, meOk, problem } from "./mocks/fixtures";
import { apiUrl } from "./mocks/handlers";
import { server } from "./mocks/server";
import { renderApp } from "./renderApp";

type Schemas = components["schemas"];

const ATHLETE = { id: "a-1", display_name: "Ana", role: "athlete" } as const;
const COACH = { id: "c-1", display_name: "Cleo", role: "coach" } as const;

const link = (over: Partial<Schemas["CoachLink"]> = {}): Schemas["CoachLink"] => ({
  id: "l-1",
  status: "pending",
  source: "request",
  coach: COACH,
  athlete: ATHLETE,
  created_at: "2026-10-31T10:00:00Z",
  updated_at: "2026-10-31T10:00:00Z",
  ...over,
});

/** A tiny fake of the link API: a mutable list plus a log of the calls it received. */
function fakeLinks(initial: Schemas["CoachLink"][] = []) {
  let items = initial;
  const calls: string[] = [];
  server.use(
    http.get(apiUrl("/coach-links"), () => HttpResponse.json({ items })),
    http.post(apiUrl("/coach-links/:id/:action"), ({ params }) => {
      const status = { approve: "active", decline: "declined", end: "ended" }[String(params.action)] as Schemas["CoachLink"]["status"];
      calls.push(`${params.action}:${params.id}`);
      const found = items.find((l) => l.id === params.id)!;
      items = items.map((l) => (l.id === params.id ? { ...l, status } : l));
      return HttpResponse.json({ ...found, status });
    }),
  );
  return { calls, set: (next: Schemas["CoachLink"][]) => (items = next) };
}

describe("athlete: find and request a coach", () => {
  beforeEach(() => server.use(meOk()));

  it("searches (3+ characters) and requests a coach, then shows the pending card", async () => {
    const queries: string[] = [];
    const posted: unknown[] = [];
    const fake = fakeLinks();
    server.use(
      http.get(apiUrl("/coaches/search"), ({ request }) => {
        queries.push(new URL(request.url).searchParams.get("q")!);
        return HttpResponse.json({ items: [{ id: "c-1", display_name: "Cleo", bio: "Strength coach" }] });
      }),
      http.post(apiUrl("/coach-links"), async ({ request }) => {
        posted.push(await request.json());
        fake.set([link()]);
        return HttpResponse.json(link(), { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderApp("/coach");

    await user.type(await screen.findByLabelText(en.coach.athlete.searchLabel), "ab");
    await user.click(screen.getByRole("button", { name: en.coach.athlete.searchButton }));
    expect(screen.getByText(en.coach.athlete.tooShort, { selector: "p" })).toBeInTheDocument();
    expect(queries).toEqual([]);

    await user.type(screen.getByLabelText(en.coach.athlete.searchLabel), "c");
    await user.click(screen.getByRole("button", { name: en.coach.athlete.searchButton }));
    const results = await screen.findByRole("list", { name: en.coach.athlete.resultsLabel });
    expect(queries).toEqual(["abc"]);
    expect(within(results).getByText("Strength coach")).toBeInTheDocument();

    await user.click(within(results).getByRole("button", { name: "Request Cleo" }));
    expect(await screen.findByRole("heading", { name: en.coach.athlete.pendingTitle })).toBeInTheDocument();
    expect(posted).toEqual([{ coach_id: "c-1" }]);
    expect(screen.getByRole("button", { name: en.coach.athlete.endLink })).toBeInTheDocument();
  });

  it("shows a message when nothing matches", async () => {
    fakeLinks();
    server.use(http.get(apiUrl("/coaches/search"), () => HttpResponse.json({ items: [] })));
    const user = userEvent.setup();
    renderApp("/coach");
    await user.type(await screen.findByLabelText(en.coach.athlete.searchLabel), "nobody");
    await user.click(screen.getByRole("button", { name: en.coach.athlete.searchButton }));
    expect(await screen.findByText(en.coach.athlete.noResults)).toBeInTheDocument();
  });

  it("explains a 409 link_exists", async () => {
    fakeLinks();
    server.use(
      http.get(apiUrl("/coaches/search"), () => HttpResponse.json({ items: [{ id: "c-1", display_name: "Cleo", bio: "" }] })),
      http.post(apiUrl("/coach-links"), () => problem(409, "link_exists")),
    );
    const user = userEvent.setup();
    renderApp("/coach");
    await user.type(await screen.findByLabelText(en.coach.athlete.searchLabel), "cleo");
    await user.click(screen.getByRole("button", { name: en.coach.athlete.searchButton }));
    await user.click(await screen.findByRole("button", { name: "Request Cleo" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(en.coach.errors.linkExists);
  });

  it("ends an active link from the coach card", async () => {
    const fake = fakeLinks([link({ status: "active" })]);
    const user = userEvent.setup();
    renderApp("/coach");
    expect(await screen.findByRole("heading", { name: en.coach.athlete.currentTitle })).toBeInTheDocument();
    expect(screen.getByText("Cleo")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: en.coach.athlete.endLink }));
    await waitFor(() => expect(fake.calls).toEqual(["end:l-1"]));
    // Back to the search form once the link is ended.
    expect(await screen.findByLabelText(en.coach.athlete.searchLabel)).toBeInTheDocument();
  });

  it("withdraws a pending request with End link", async () => {
    const fake = fakeLinks([link()]);
    const user = userEvent.setup();
    renderApp("/coach");
    expect(await screen.findByRole("heading", { name: en.coach.athlete.pendingTitle })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: en.coach.athlete.endLink }));
    await waitFor(() => expect(fake.calls).toEqual(["end:l-1"]));
  });

  it("tells the athlete when the request is no longer pending", async () => {
    fakeLinks([link()]);
    server.use(http.post(apiUrl("/coach-links/:id/end"), () => problem(409, "link_not_pending")));
    const user = userEvent.setup();
    renderApp("/coach");
    await user.click(await screen.findByRole("button", { name: en.coach.athlete.endLink }));
    expect(await screen.findByRole("alert")).toHaveTextContent(en.coach.errors.notPending);
  });
});

describe("coach: profile and requests", () => {
  beforeEach(() => server.use(meOk(meFixture({ role: "coach", display_name: "Cleo", id: "c-1" }))));

  it("loads and saves the profile", async () => {
    const puts: unknown[] = [];
    fakeLinks();
    server.use(
      http.get(apiUrl("/coach/profile"), () =>
        HttpResponse.json({ user_id: "c-1", display_name: "Cleo", bio: "Old bio", discoverable: true }),
      ),
      http.put(apiUrl("/coach/profile"), async ({ request }) => {
        const body = (await request.json()) as { bio: string; discoverable: boolean };
        puts.push(body);
        return HttpResponse.json({ user_id: "c-1", display_name: "Cleo", ...body });
      }),
    );
    const user = userEvent.setup();
    renderApp("/coach");
    const bio = await screen.findByLabelText(en.coach.coach.bioLabel);
    expect(bio).toHaveValue("Old bio");
    expect(screen.getByLabelText(en.coach.coach.discoverable)).toBeChecked();
    await user.clear(bio);
    await user.type(bio, "New bio");
    await user.click(screen.getByLabelText(en.coach.coach.discoverable));
    await user.click(screen.getByRole("button", { name: en.coach.coach.save }));
    expect(await screen.findByText(en.coach.coach.saved)).toBeInTheDocument();
    expect(puts).toEqual([{ bio: "New bio", discoverable: false }]);
  });

  it("shows an error when the profile is rejected", async () => {
    fakeLinks();
    server.use(
      http.get(apiUrl("/coach/profile"), () => HttpResponse.json({ user_id: "c-1", display_name: "Cleo", bio: "", discoverable: true })),
      http.put(apiUrl("/coach/profile"), () => problem(422, "validation_error")),
    );
    const user = userEvent.setup();
    renderApp("/coach");
    await user.click(await screen.findByRole("button", { name: en.coach.coach.save }));
    expect(await screen.findByRole("alert")).toHaveTextContent(en.coach.coach.saveFailed);
  });

  function profileOk() {
    server.use(
      http.get(apiUrl("/coach/profile"), () => HttpResponse.json({ user_id: "c-1", display_name: "Cleo", bio: "", discoverable: true })),
    );
  }

  it("approves an incoming request and then lists the athlete with End link", async () => {
    profileOk();
    const fake = fakeLinks([link()]);
    const user = userEvent.setup();
    renderApp("/coach");
    expect(await screen.findByText(en.coach.coach.incomingBody.replace("{{name}}", "Ana"))).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: en.coach.coach.approve }));
    await waitFor(() => expect(fake.calls).toEqual(["approve:l-1"]));
    expect(await screen.findByText(en.coach.coach.noIncoming)).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "End link with Ana" }));
    await waitFor(() => expect(fake.calls).toEqual(["approve:l-1", "end:l-1"]));
    expect(await screen.findByText(en.coach.coach.noAthletes)).toBeInTheDocument();
  });

  it("declines an incoming request", async () => {
    profileOk();
    const fake = fakeLinks([link()]);
    const user = userEvent.setup();
    renderApp("/coach");
    await user.click(await screen.findByRole("button", { name: en.coach.coach.decline }));
    await waitFor(() => expect(fake.calls).toEqual(["decline:l-1"]));
    expect(await screen.findByText(en.coach.coach.noIncoming)).toBeInTheDocument();
  });

  it("explains a request that was withdrawn meanwhile", async () => {
    profileOk();
    fakeLinks([link()]);
    server.use(http.post(apiUrl("/coach-links/:id/approve"), () => problem(409, "link_not_pending")));
    const user = userEvent.setup();
    renderApp("/coach");
    await user.click(await screen.findByRole("button", { name: en.coach.coach.approve }));
    expect(await screen.findByRole("alert")).toHaveTextContent(en.coach.errors.notPending);
  });
});
