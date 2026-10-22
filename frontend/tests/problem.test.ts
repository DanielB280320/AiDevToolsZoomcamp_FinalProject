import { describe, expect, it } from "vitest";

import {
  problemFromResponse,
  type ProblemDetails,
  toProblemDetails,
  UNKNOWN_PROBLEM_CODE,
} from "../src/api/problem";

const unknown: ProblemDetails = { code: UNKNOWN_PROBLEM_CODE, detail: "", fieldErrors: {} };

// Bodies taken from the examples in openapi.yaml (components.responses).
const validationProblem = {
  type: "/problems/validation_error",
  title: "Validation failed",
  status: 422,
  code: "validation_error",
  detail: "Some values are outside the allowed range.",
  errors: [
    { field: "body_metric.weight_kg", code: "out_of_range", message: "Weight must be between 35 and 300 kg." },
  ],
};

describe("toProblemDetails", () => {
  it.each<[string, unknown, ProblemDetails]>([
    [
      "validation error with one field",
      validationProblem,
      {
        code: "validation_error",
        detail: "Some values are outside the allowed range.",
        fieldErrors: { "body_metric.weight_kg": "Weight must be between 35 and 300 kg." },
      },
    ],
    [
      "problem without errors",
      { type: "/problems/email_taken", title: "Conflict", status: 409, code: "email_taken", detail: "An account with this email already exists." },
      { code: "email_taken", detail: "An account with this email already exists.", fieldErrors: {} },
    ],
    [
      "problem without detail falls back to title",
      { type: "/problems/forbidden", title: "Forbidden", status: 403, code: "forbidden" },
      { code: "forbidden", detail: "Forbidden", fieldErrors: {} },
    ],
    [
      "several errors on different fields, and the first message wins per field",
      {
        ...validationProblem,
        errors: [
          { field: "email", code: "required", message: "Enter your email." },
          { field: "password", code: "too_short", message: "Use at least 10 characters." },
          { field: "email", code: "invalid", message: "Second message for email." },
        ],
      },
      {
        code: "validation_error",
        detail: validationProblem.detail,
        fieldErrors: { email: "Enter your email.", password: "Use at least 10 characters." },
      },
    ],
    [
      "malformed entries in errors are skipped",
      { ...validationProblem, errors: [null, "x", { field: "a" }, { message: "m" }, { field: "ok", code: "c", message: "Fine." }] },
      { code: "validation_error", detail: validationProblem.detail, fieldErrors: { ok: "Fine." } },
    ],
    ["errors that is not an array is ignored", { ...validationProblem, errors: "nope" }, { code: "validation_error", detail: validationProblem.detail, fieldErrors: {} }],
    ["undefined body", undefined, unknown],
    ["null body", null, unknown],
    ["string body", "Bad Gateway", unknown],
    ["array body", [validationProblem], unknown],
    ["object without code", { title: "Not Found", status: 404 }, unknown],
  ])("%s", (_name, body, expected) => {
    expect(toProblemDetails(body)).toEqual(expected);
  });
});

describe("problemFromResponse", () => {
  it("maps an application/problem+json response", async () => {
    const response = new Response(JSON.stringify(validationProblem), {
      status: 422,
      headers: { "Content-Type": "application/problem+json; charset=utf-8" },
    });

    expect(await problemFromResponse(response)).toEqual({
      code: "validation_error",
      detail: "Some values are outside the allowed range.",
      fieldErrors: { "body_metric.weight_kg": "Weight must be between 35 and 300 kg." },
    });
  });

  it.each([
    ["an HTML error page", new Response("<h1>502</h1>", { status: 502, headers: { "Content-Type": "text/html" } })],
    ["a problem content type with invalid JSON", new Response("{", { status: 500, headers: { "Content-Type": "application/problem+json" } })],
    ["a response without content type", new Response(null, { status: 500 })],
  ])("returns the unknown problem for %s", async (_name, response) => {
    expect(await problemFromResponse(response)).toEqual(unknown);
  });
});
