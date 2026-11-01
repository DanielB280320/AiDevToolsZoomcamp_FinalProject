// QA (#49): the not-linked page polls the active links every 15 s on its own (no "Check again"
// click) and does not loop: between polls it sends no extra requests.
import { act, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { components } from "../src/api/schema";
import { meFixture, meOk } from "./mocks/fixtures";
import { apiUrl } from "./mocks/handlers";
import { server } from "./mocks/server";
import { renderApp } from "./renderApp";

const COACH = meFixture({ id: "c-1", display_name: "Cleo", role: "coach" });
const alice: components["schemas"]["CoachAthleteSummary"] = {
  athlete: { id: "a-1", display_name: "Alice", role: "athlete" },
  units: "metric",
  timezone: "Europe/Madrid",
  link_id: "l-1",
  linked_since: "2026-10-01T10:00:00Z",
  needs_attention: false,
  attention_reasons: [],
  training_adherence_7d: 0.85,
  last_log_date: "2026-10-24",
  pending_suggestion_count: 0,
};

afterEach(() => {
  vi.useRealTimers();
});

describe("coach shell re-link poll (QA #49)", () => {
  it("refetches the active links on the 15 s timer without looping and shows the client after a re-link", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let linked = false;
    let listCalls = 0;
    const athleteData: string[] = [];
    server.events.on("request:start", ({ request }) => {
      const path = new URL(request.url).pathname;
      if (path.includes("/athletes/a-1/")) athleteData.push(path);
    });
    server.use(
      meOk(COACH),
      http.get(apiUrl("/coach/athletes"), () => {
        listCalls += 1;
        return HttpResponse.json({ items: linked ? [alice] : [] });
      }),
    );
    renderApp("/coach/clients/a-1");
    expect(await screen.findByTestId("not-linked")).toBeInTheDocument();
    const afterLoad = listCalls;
    // No loop: well inside one poll interval nothing else is requested.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(listCalls).toBe(afterLoad);
    // The timer fires once per 15 s.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_500);
    });
    expect(listCalls).toBe(afterLoad + 1);
    expect(screen.getByTestId("not-linked")).toBeInTheDocument();
    expect(athleteData).toEqual([]);
    // The athlete re-links: the next poll brings the client back without a click.
    linked = true;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15_500);
    });
    expect(await screen.findByRole("region", { name: "Athlete you are viewing" })).toBeInTheDocument();
    expect(screen.queryByTestId("not-linked")).not.toBeInTheDocument();
    // Polling stops once the client shows.
    const whenShown = listCalls;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(31_000);
    });
    expect(listCalls).toBe(whenShown);
  });
});
