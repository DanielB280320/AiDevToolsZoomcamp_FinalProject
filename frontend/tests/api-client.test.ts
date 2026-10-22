import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { API_BASE_URL, api, createApiClient } from "../src/api/client";
import { apiUrl } from "./mocks/handlers";
import { server } from "./mocks/server";

describe("generated API client", () => {
  it("uses /api/v1 as base URL", () => {
    expect(API_BASE_URL).toBe("/api/v1");
  });

  it("sends requests to /api/v1/<path> with cookie credentials", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");

    const { data } = await api.GET("/healthz");

    expect(data).toEqual({ status: "ok" }); // answered by the mock server, not the network
    const sent = fetchSpy.mock.calls[0]![0] as Request;
    expect(new URL(sent.url).pathname).toBe("/api/v1/healthz");
    expect(new URL(sent.url).origin).toBe(window.location.origin);
    expect(sent.credentials).toBe("include");
  });

  it("keeps base URL and credentials even when callers pass other options", async () => {
    const requests: Request[] = [];
    const client = createApiClient({
      fetch: async (request: Request) => {
        requests.push(request);
        return Response.json({ status: "ok" });
      },
    });

    await client.GET("/healthz");

    expect(new URL(requests[0]!.url).pathname).toBe("/api/v1/healthz");
    expect(requests[0]!.credentials).toBe("include");
  });

  it("returns the problem body as `error` for non-2xx responses", async () => {
    server.use(
      http.get(apiUrl("/me"), () =>
        HttpResponse.json(
          { type: "/problems/not_authenticated", title: "Unauthorized", status: 401, code: "not_authenticated" },
          { status: 401, headers: { "Content-Type": "application/problem+json" } },
        ),
      ),
    );

    const { data, error, response } = await api.GET("/me");

    expect(data).toBeUndefined();
    expect(response.status).toBe(401);
    expect(error).toMatchObject({ code: "not_authenticated" });
  });

  it("fails unmocked requests instead of reaching the network", async () => {
    await expect(api.GET("/readyz")).rejects.toThrow();
  });
});
