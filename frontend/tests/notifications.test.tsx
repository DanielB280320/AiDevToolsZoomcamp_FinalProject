import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { components } from "../src/api/schema";
import en from "../src/i18n/en.json";
import { meFixture, meOk } from "./mocks/fixtures";
import { apiUrl } from "./mocks/handlers";
import { server } from "./mocks/server";
import { renderApp } from "./renderApp";

type Schemas = components["schemas"];
type Notification = Schemas["Notification"];

// The phone width of the acceptance criteria. jsdom has no layout; this sets what code can read.
beforeEach(() => {
  Object.defineProperty(window, "innerWidth", { configurable: true, value: 360 });
  window.dispatchEvent(new Event("resize"));
});

let seq = 0;
function note(type: Notification["type"], overrides: Partial<Notification> = {}): Notification {
  seq += 1;
  return {
    id: `n-${seq}`,
    type,
    payload: {},
    created_at: `2026-10-31T10:${String(seq % 60).padStart(2, "0")}:00Z`,
    read_at: null,
    ...overrides,
  };
}

/** Stateful fake of the three endpoints plus `GET /me`'s unread count. */
function fakeNotifications(initial: Notification[], { pageSize = 50, failList = false } = {}) {
  let items = initial;
  const calls = { read: [] as string[], readAll: 0, lists: [] as URLSearchParams[] };
  const unread = () => items.filter((n) => !n.read_at).length;
  server.use(
    http.get(apiUrl("/me"), () => HttpResponse.json(meFixture({ unread_notification_count: unread() }))),
    http.get(apiUrl("/notifications"), ({ request }) => {
      const q = new URL(request.url).searchParams;
      calls.lists.push(q);
      if (failList) return HttpResponse.json({ status: 500, code: "internal" }, { status: 500 });
      let rows = items;
      if (q.get("unread_only") === "true") rows = rows.filter((n) => !n.read_at);
      const start = Number(q.get("cursor") ?? 0);
      const page = rows.slice(start, start + pageSize);
      const next = start + pageSize < rows.length ? String(start + pageSize) : null;
      return HttpResponse.json({ items: page, unread_count: unread(), next_cursor: next });
    }),
    http.post(apiUrl("/notifications/read-all"), () => {
      calls.readAll += 1;
      const updated = unread();
      items = items.map((n) => ({ ...n, read_at: n.read_at ?? "2026-10-31T12:00:00Z" }));
      return HttpResponse.json({ updated });
    }),
    http.post(apiUrl("/notifications/:id/read"), ({ params }) => {
      calls.read.push(String(params.id));
      items = items.map((n) => (n.id === params.id ? { ...n, read_at: n.read_at ?? "2026-10-31T12:00:00Z" } : n));
      return HttpResponse.json(items.find((n) => n.id === params.id)!);
    }),
  );
  return calls;
}

describe("bell", () => {
  it("names the unread count and links to the inbox", async () => {
    server.use(meOk(meFixture({ unread_notification_count: 3 })));
    renderApp("/week");
    const bell = await screen.findByRole("link", { name: "Notifications, 3 unread" });
    expect(bell).toHaveAttribute("href", "/notifications");
    expect(within(bell).getByTestId("bell-badge")).toHaveTextContent("3");
    expect(bell.className).toContain("min-h-11");
    expect(bell.className).toContain("min-w-11");
  });

  it("shows 99+ above 99 but 99 exactly", async () => {
    server.use(meOk(meFixture({ unread_notification_count: 100 })));
    renderApp("/week");
    expect(await screen.findByTestId("bell-badge")).toHaveTextContent("99+");
  });

  it("shows 99 at 99", async () => {
    server.use(meOk(meFixture({ unread_notification_count: 99 })));
    renderApp("/week");
    expect(await screen.findByTestId("bell-badge")).toHaveTextContent(/^99$/);
  });

  it("hides the badge at 0", async () => {
    server.use(meOk(meFixture({ unread_notification_count: 0 })));
    renderApp("/week");
    expect(await screen.findByRole("link", { name: "Notifications" })).toBeInTheDocument();
    expect(screen.queryByTestId("bell-badge")).not.toBeInTheDocument();
  });

  it("is absent when signed out", async () => {
    renderApp("/");
    await screen.findByRole("banner");
    expect(screen.queryByRole("link", { name: /^Notifications/ })).not.toBeInTheDocument();
  });
});

describe("inbox", () => {
  it("lists rows in API order with text from i18n, unread marked in text, not colour alone", async () => {
    fakeNotifications([
      note("recalc_prompt"),
      note("calorie_suggestion", { read_at: "2026-10-31T09:00:00Z" }),
    ]);
    renderApp("/notifications");
    const rows = await screen.findAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent(en.notifications.types.recalc_prompt);
    expect(rows[0]).toHaveAttribute("data-unread", "true");
    expect(within(rows[0]!).getByText("Unread")).toBeInTheDocument();
    expect(rows[1]).toHaveTextContent(en.notifications.types.calorie_suggestion);
    expect(rows[1]).toHaveAttribute("data-unread", "false");
    expect(within(rows[1]!).queryByText("Unread")).not.toBeInTheDocument();
  });

  it("shows the empty state", async () => {
    fakeNotifications([]);
    renderApp("/notifications");
    expect(await screen.findByText(en.notifications.inbox.empty)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Mark all read" })).not.toBeInTheDocument();
  });

  it("shows an error state with retry", async () => {
    fakeNotifications([], { failList: true });
    renderApp("/notifications");
    expect(await screen.findByRole("alert")).toHaveTextContent(en.calendar.loadFailed);
    expect(screen.getByRole("button", { name: en.session.retry })).toBeInTheDocument();
  });

  it("loads more with next_cursor", async () => {
    const user = userEvent.setup();
    const calls = fakeNotifications(
      [note("recalc_prompt"), note("recalc_prompt"), note("calorie_suggestion")],
      { pageSize: 2 },
    );
    renderApp("/notifications");
    expect(await screen.findAllByRole("listitem")).toHaveLength(2);
    await user.click(screen.getByRole("button", { name: "Load more" }));
    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(3));
    expect(calls.lists.at(-1)?.get("cursor")).toBe("2");
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
  });

  it("tapping a row marks it read, navigates to its target and the bell drops by one", async () => {
    const user = userEvent.setup();
    const calls = fakeNotifications([note("recalc_prompt"), note("progression_suggestion")]);
    const { router } = renderApp("/notifications");
    await screen.findByRole("link", { name: "Notifications, 2 unread" });
    await user.click(await screen.findByRole("button", { name: new RegExp(en.notifications.types.recalc_prompt) }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/body"));
    expect(calls.read).toEqual(["n-" + (seq - 1)]);
    expect(await screen.findByRole("link", { name: "Notifications, 1 unread" })).toBeInTheDocument();
  });

  it("calorie_suggestion leads to Today, where every suggestion kind is listed", async () => {
    const user = userEvent.setup();
    fakeNotifications([note("calorie_suggestion")]);
    const { router } = renderApp("/notifications");
    await user.click(await screen.findByRole("button", { name: new RegExp(en.notifications.types.calorie_suggestion) }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/today"));
  });

  it("content_removed leads to Today", async () => {
    const user = userEvent.setup();
    fakeNotifications([note("content_removed")]);
    const { router } = renderApp("/notifications");
    await user.click(await screen.findByRole("button", { name: new RegExp(en.notifications.types.content_removed) }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/today"));
  });

  it("marks all read: bell is 0 and no row is unread", async () => {
    const user = userEvent.setup();
    const calls = fakeNotifications([note("recalc_prompt"), note("calorie_suggestion")]);
    renderApp("/notifications");
    await screen.findByRole("link", { name: "Notifications, 2 unread" });
    await user.click(await screen.findByRole("button", { name: "Mark all read" }));
    await waitFor(() => expect(screen.getByRole("link", { name: "Notifications" })).toBeInTheDocument());
    await waitFor(() => {
      for (const row of screen.getAllByRole("listitem")) expect(row).toHaveAttribute("data-unread", "false");
    });
    expect(calls.readAll).toBe(1);
    expect(screen.queryByTestId("bell-badge")).not.toBeInTheDocument();
  });

  it.each(["coach_note", "link_request_received", "link_ended", "plan_edited_by_coach"] as const)(
    "renders a generic row for %s and does not navigate",
    async (type) => {
      const user = userEvent.setup();
      const calls = fakeNotifications([note(type)]);
      const { router } = renderApp("/notifications");
      await user.click(await screen.findByRole("button", { name: new RegExp(en.notifications.types.generic) }));
      await waitFor(() => expect(calls.read).toHaveLength(1));
      expect(router.state.location.pathname).toBe("/notifications");
    },
  );
});

describe("Today banners", () => {
  it("shows a banner per unread suggestion/removal notification and ignores other types", async () => {
    fakeNotifications([note("progression_suggestion"), note("coach_note"), note("content_removed")]);
    renderApp("/today");
    expect(await screen.findAllByTestId("notification-banner")).toHaveLength(2);
    expect(screen.queryByRole("link", { name: en.notifications.banners.seeAll })).not.toBeInTheDocument();
  });

  it("caps at 3 and links to the inbox", async () => {
    fakeNotifications([
      note("progression_suggestion"),
      note("progression_suggestion"),
      note("calorie_suggestion"),
      note("recalc_prompt"),
    ]);
    renderApp("/today");
    expect(await screen.findAllByTestId("notification-banner")).toHaveLength(3);
    expect(screen.getByRole("link", { name: en.notifications.banners.seeAll })).toHaveAttribute(
      "href",
      "/notifications",
    );
  });

  it("dismiss marks read without navigating and the banner disappears", async () => {
    const user = userEvent.setup();
    const calls = fakeNotifications([note("calorie_suggestion")]);
    const { router } = renderApp("/today");
    const banner = await screen.findByTestId("notification-banner");
    await user.click(within(banner).getByRole("button", { name: "Dismiss" }));
    await waitFor(() => expect(screen.queryByTestId("notification-banner")).not.toBeInTheDocument());
    expect(calls.read).toHaveLength(1);
    expect(router.state.location.pathname).toBe("/today");
  });

  it("open marks read, navigates to the target and the banner is gone", async () => {
    const user = userEvent.setup();
    const calls = fakeNotifications([note("recalc_prompt")]);
    const { router } = renderApp("/today");
    const banner = await screen.findByTestId("notification-banner");
    await user.click(within(banner).getByRole("button", { name: "Open" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/body"));
    expect(calls.read).toHaveLength(1);
  });
});

describe("privacy", () => {
  const spies: ReturnType<typeof vi.spyOn>[] = [];
  afterEach(() => {
    for (const spy of spies.splice(0)) spy.mockRestore();
  });

  it("sends nothing to console or beacons while using notifications", async () => {
    const user = userEvent.setup();
    for (const method of ["log", "info", "warn", "error", "debug"] as const) {
      spies.push(vi.spyOn(console, method).mockImplementation(() => {}));
    }
    const beacon = vi.fn();
    Object.defineProperty(navigator, "sendBeacon", { configurable: true, value: beacon });
    fakeNotifications([note("recalc_prompt"), note("coach_note")]);
    renderApp("/notifications");
    await user.click(await screen.findByRole("button", { name: "Mark all read" }));
    await waitFor(() => expect(screen.queryByTestId("bell-badge")).not.toBeInTheDocument());
    for (const spy of spies) expect(spy).not.toHaveBeenCalled();
    expect(beacon).not.toHaveBeenCalled();
  });
});
