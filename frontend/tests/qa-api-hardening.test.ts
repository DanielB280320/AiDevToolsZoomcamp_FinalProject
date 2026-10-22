import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { api } from "../src/api/client";
import { problemFromResponse, toProblemDetails } from "../src/api/problem";
import { apiUrl } from "./mocks/handlers";
import { server } from "./mocks/server";

describe("no real network in tests (CLAUDE.md rule 4)", () => {
  it("rejects unmocked requests in MSW itself, before any socket is opened", async () => {
    const error = await api.GET("/readyz").then(
      () => undefined,
      (e: unknown) => e as Error & { cause?: unknown },
    );

    expect(error).toBeInstanceOf(TypeError);
    // A refused connection would also reject; the cause proves MSW blocked the request.
    expect(String(error?.cause)).toContain("[MSW]");
    expect(String(error?.cause)).toContain("onUnhandledFrame");
  });
});

describe("generated client and problem-details helper together (#9 usage)", () => {
  const validationProblem = {
    type: "/problems/validation_error",
    title: "Validation failed",
    status: 422,
    code: "validation_error",
    detail: "Some values are outside the allowed range.",
    errors: [{ field: "height_cm", code: "out_of_range", message: "Height must be between 120 and 230 cm." }],
  };

  it("maps the `error` of a 422 problem+json response from api.PATCH /me", async () => {
    server.use(
      http.patch(apiUrl("/me"), () =>
        HttpResponse.json(validationProblem, {
          status: 422,
          headers: { "Content-Type": "application/problem+json" },
        }),
      ),
    );

    const { error, response } = await api.PATCH("/me", { body: {} });

    expect(response.status).toBe(422);
    expect(toProblemDetails(error)).toEqual({
      code: "validation_error",
      detail: "Some values are outside the allowed range.",
      fieldErrors: { height_cm: "Height must be between 120 and 230 cm." },
    });
  });

  it("sends cookie credentials on mutating requests too", async () => {
    server.use(http.post(apiUrl("/auth/logout"), () => new HttpResponse(null, { status: 204 })));
    const fetchSpy = vi.spyOn(globalThis, "fetch");

    await api.POST("/auth/logout");

    const sent = fetchSpy.mock.calls[0]![0] as Request;
    expect(sent.method).toBe("POST");
    expect(new URL(sent.url).pathname).toBe("/api/v1/auth/logout");
    expect(sent.credentials).toBe("include");
  });

  it("treats the problem content type case-insensitively", async () => {
    const response = new Response(JSON.stringify(validationProblem), {
      status: 422,
      headers: { "Content-Type": "Application/Problem+JSON" },
    });

    expect((await problemFromResponse(response)).code).toBe("validation_error");
  });
});
