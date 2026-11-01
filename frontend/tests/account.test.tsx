import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "../src/i18n/en.json";
import { meFixture, meOk, problem } from "./mocks/fixtures";
import { apiUrl } from "./mocks/handlers";
import { server } from "./mocks/server";
import { renderApp } from "./renderApp";

describe("account page (F18)", () => {
  const created = vi.fn(() => "blob:fitwise");
  const revoked = vi.fn();
  let clicked: { download: string; href: string }[] = [];

  beforeEach(() => {
    clicked = [];
    Object.defineProperty(URL, "createObjectURL", { value: created, configurable: true });
    Object.defineProperty(URL, "revokeObjectURL", { value: revoked, configurable: true });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push({ download: this.download, href: this.href });
    });
  });
  afterEach(() => vi.restoreAllMocks());

  it("export downloads the ZIP under the server's file name", async () => {
    server.use(
      meOk(),
      http.get(
        apiUrl("/me/export"),
        () =>
          new HttpResponse(new Uint8Array([80, 75, 3, 4]), {
            headers: {
              "Content-Type": "application/zip",
              "Content-Disposition": 'attachment; filename="fitwise-export-2026-11-01.zip"',
            },
          }),
      ),
    );
    const user = userEvent.setup();
    renderApp("/account");

    await user.click(await screen.findByRole("button", { name: en.account.export.button }));

    await waitFor(() => expect(clicked).toHaveLength(1));
    expect(clicked[0]?.download).toBe("fitwise-export-2026-11-01.zip");
    expect(created).toHaveBeenCalled();
    expect(revoked).toHaveBeenCalled();
  });

  it("shows an error when the export fails", async () => {
    server.use(meOk(), http.get(apiUrl("/me/export"), () => problem(500, "internal_error")));
    const user = userEvent.setup();
    renderApp("/account");

    await user.click(await screen.findByRole("button", { name: en.account.export.button }));

    expect(await screen.findByText(en.account.export.failed)).toBeInTheDocument();
    expect(clicked).toHaveLength(0);
  });

  it("deleting needs the password, shows a 403 as a wrong password and keeps the session", async () => {
    let calls = 0;
    server.use(
      meOk(),
      http.post(apiUrl("/me/delete"), () => {
        calls += 1;
        return problem(403, "forbidden");
      }),
    );
    const user = userEvent.setup();
    const { router } = renderApp("/account");

    await user.click(await screen.findByRole("button", { name: en.account.delete.open }));
    await user.click(screen.getByRole("button", { name: en.account.delete.submit }));
    expect(await screen.findByText(en.account.delete.required)).toBeInTheDocument();
    expect(calls).toBe(0);

    await user.type(screen.getByLabelText(en.account.delete.password), "wrong-password-1");
    await user.click(screen.getByRole("button", { name: en.account.delete.submit }));

    expect(await screen.findByText(en.account.delete.wrongPassword)).toBeInTheDocument();
    expect(calls).toBe(1);
    expect(router.state.location.pathname).toBe("/account");
  });

  it("on success sends the password, signs out and lands on the sign-in page", async () => {
    let deleted = false;
    let sent: unknown;
    server.use(
      http.get(apiUrl("/me"), () => (deleted ? problem(401, "not_authenticated") : HttpResponse.json(meFixture()))),
      http.post(apiUrl("/me/delete"), async ({ request }) => {
        sent = await request.json();
        deleted = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    const { router } = renderApp("/account");

    await user.click(await screen.findByRole("button", { name: en.account.delete.open }));
    await user.type(screen.getByLabelText(en.account.delete.password), "correct-horse-battery");
    await user.click(screen.getByRole("button", { name: en.account.delete.submit }));

    expect(await screen.findByRole("heading", { level: 1, name: en.auth.signIn.title })).toBeInTheDocument();
    expect(sent).toEqual({ password: "correct-horse-battery" });
    expect(router.state.location.pathname).toBe("/sign-in");
    expect(screen.queryByRole("button", { name: en.nav.signOut })).not.toBeInTheDocument();
  });
});
