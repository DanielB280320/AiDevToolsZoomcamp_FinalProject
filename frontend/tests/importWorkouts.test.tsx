import { File as NodeFile } from "node:buffer";

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "../src/i18n/en.json";
import { meOk, problem } from "./mocks/fixtures";
import { apiUrl } from "./mocks/handlers";
import { server } from "./mocks/server";
import { renderApp } from "./renderApp";

const IMPORT_PATH = "/athletes/me/imports/workouts";
// jsdom's File and FormData cannot be streamed by Node's fetch ("premature close"), so these
// tests use Node's own classes; a browser sends the real ones.
const csv = () => new NodeFile(["date,exercise\n"], "workouts.csv", { type: "text/csv" }) as unknown as File;

async function chooseAndImport(user: ReturnType<typeof userEvent.setup>) {
  await user.upload(await screen.findByLabelText(en.account.import.file), csv());
  await user.click(screen.getByRole("button", { name: en.account.import.button }));
}

describe("settings: import past workouts (F10.5)", () => {
  beforeEach(async () => {
    const form = await new Response("a=1", {
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
    }).formData();
    vi.stubGlobal("FormData", form.constructor);
  });
  afterEach(() => vi.unstubAllGlobals());

  it("uploads the file and shows the imported and skipped counts", async () => {
    let received = { type: "", body: "" };
    server.use(
      meOk(),
      http.post(apiUrl(IMPORT_PATH), async ({ request }) => {
        received = { type: request.headers.get("Content-Type") ?? "", body: await request.text() };
        return HttpResponse.json({ imported: 12, skipped: 3 });
      }),
    );
    const user = userEvent.setup();
    renderApp("/account");

    await chooseAndImport(user);

    expect(await screen.findByText("Imported 12 sets, skipped 3 already imported.")).toBeInTheDocument();
    expect(received.type).toMatch(/^multipart\/form-data; boundary=/);
    expect(received.body).toContain('name="file"; filename="workouts.csv"');
    expect(received.body).toContain("date,exercise");
  });

  it("asks for a file before uploading", async () => {
    let calls = 0;
    server.use(
      meOk(),
      http.post(apiUrl(IMPORT_PATH), () => {
        calls += 1;
        return HttpResponse.json({ imported: 0, skipped: 0 });
      }),
    );
    const user = userEvent.setup();
    renderApp("/account");

    await user.click(await screen.findByRole("button", { name: en.account.import.button }));

    expect(await screen.findByText(en.account.import.chooseFile)).toBeInTheDocument();
    expect(calls).toBe(0);
  });

  it("lists the row errors of a rejected file", async () => {
    server.use(
      meOk(),
      http.post(apiUrl(IMPORT_PATH), () =>
        problem(422, "invalid_import", {
          errors: [
            { field: "rows.3", code: "invalid_row", message: "unknown exercise" },
            { field: "rows.9", code: "invalid_row", message: "date is in the future" },
          ],
        }),
      ),
    );
    const user = userEvent.setup();
    renderApp("/account");

    await chooseAndImport(user);

    expect(await screen.findByText(en.account.import.rowsHeading)).toBeInTheDocument();
    expect(screen.getByText("Row 3: unknown exercise")).toBeInTheDocument();
    expect(screen.getByText("Row 9: date is in the future")).toBeInTheDocument();
  });

  it.each([
    [413, "file_too_large", en.account.import.tooLarge],
    [422, "too_many_rows", en.account.import.tooManyRows],
    [500, "internal_error", en.account.import.failed],
  ])("explains a %i %s response", async (status, code, message) => {
    server.use(meOk(), http.post(apiUrl(IMPORT_PATH), () => problem(status, code)));
    const user = userEvent.setup();
    renderApp("/account");

    await chooseAndImport(user);

    expect(await screen.findByText(message)).toBeInTheDocument();
  });
});
