import { screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import en from "../src/i18n/en.json";
import { apiUrl } from "./mocks/handlers";
import { server } from "./mocks/server";
import { renderApp } from "./renderApp";

describe("app shell", () => {
  it.each(["/", "/no-such-page"])("renders header, main content and footer on %s", async (path) => {
    renderApp(path);

    expect(await screen.findByRole("banner")).toBeInTheDocument();
    expect(screen.getByRole("main")).toBeInTheDocument();
    expect(screen.getByRole("contentinfo")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: en.app.homeLink })).toHaveAttribute("href", "/");
  });

  it.each(["/", "/no-such-page"])("shows the spec §6.3 disclaimer in the footer on %s", async (path) => {
    renderApp(path);

    const footer = await screen.findByRole("contentinfo");
    expect(footer).toHaveTextContent(en.footer.disclaimer);
  });

  it("offers a skip link to the main content", async () => {
    renderApp("/");

    const skip = await screen.findByRole("link", { name: en.app.skipToContent });
    expect(skip).toHaveAttribute("href", `#${screen.getByRole("main").id}`);
  });

  it("shows the not-found page for unknown routes", async () => {
    renderApp("/no-such-page");

    expect(await screen.findByRole("heading", { level: 1, name: en.notFound.title })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: en.notFound.backHome })).toHaveAttribute("href", "/");
  });
});

describe("home page", () => {
  it("reports the service as running when /healthz answers ok", async () => {
    renderApp("/");

    expect(screen.getByRole("heading", { level: 1, name: en.home.title })).toBeInTheDocument();
    expect(await screen.findByText(en.home.status.ok)).toBeInTheDocument();
  });

  it("reports the service as unreachable when /healthz fails", async () => {
    server.use(http.get(apiUrl("/healthz"), () => new HttpResponse(null, { status: 502 })));
    renderApp("/");

    expect(await screen.findByText(en.home.status.down)).toBeInTheDocument();
  });
});
