import i18n from "i18next";
import { describe, expect, it } from "vitest";

import { ApiError, parseRetryAfter } from "../src/api/errors";
import { toProblemDetails } from "../src/api/problem";
import {
  firstErrorField,
  problemToFormErrors,
  rateLimitedMessage,
  SIGN_IN_FIELDS,
  SIGN_UP_FIELDS,
  type SignUpValues,
  validateSignIn,
  validateSignUp,
} from "../src/auth/forms";
import en from "../src/i18n/en.json";

const t = i18n.t.bind(i18n);

const valid: SignUpValues = {
  email: "ana@example.com",
  password: "correct-horse",
  display_name: "Ana",
  role: "athlete",
  birth_date: "1995-04-12",
  units: "metric",
  timezone: "Europe/Madrid",
  accept_disclaimer: true,
};

const apiError = (status: number, body: unknown, retryAfter: number | null = null) =>
  new ApiError(status, toProblemDetails(body), retryAfter);

describe("validateSignUp mirrors SignUpRequest", () => {
  it("accepts a complete, valid form", () => {
    expect(validateSignUp(valid, t)).toEqual({});
  });

  it.each<[string, Partial<SignUpValues>, Partial<Record<keyof SignUpValues, string>>]>([
    ["empty email", { email: "  " }, { email: en.auth.validation.emailRequired }],
    ["malformed email", { email: "ana@example" }, { email: en.auth.validation.emailInvalid }],
    ["empty password", { password: "" }, { password: en.auth.validation.passwordRequired }],
    ["9-character password", { password: "123456789" }, { password: "Use at least 10 characters." }],
    ["129-character password", { password: "x".repeat(129) }, { password: "Use at most 128 characters." }],
    ["blank display name", { display_name: "   " }, { display_name: en.auth.validation.displayNameRequired }],
    ["61-character display name", { display_name: "a".repeat(61) }, { display_name: "Use at most 60 characters." }],
    ["no role", { role: "" }, { role: en.auth.validation.roleRequired }],
    ["no date of birth", { birth_date: "" }, { birth_date: en.auth.validation.birthDateRequired }],
    ["no units", { units: "" }, { units: en.auth.validation.unitsRequired }],
    ["no time zone", { timezone: "" }, { timezone: en.auth.validation.timezoneRequired }],
    ["disclaimer not accepted", { accept_disclaimer: false }, { accept_disclaimer: en.auth.validation.disclaimerRequired }],
  ])("rejects %s", (_, change, expected) => {
    expect(validateSignUp({ ...valid, ...change }, t)).toEqual(expected);
  });

  it("accepts a password of exactly 10 characters", () => {
    expect(validateSignUp({ ...valid, password: "1234567890" }, t)).toEqual({});
  });
});

describe("validateSignIn mirrors LogInRequest", () => {
  it("requires email and password but not a minimum password length", () => {
    expect(validateSignIn({ email: "", password: "" }, t)).toEqual({
      email: en.auth.validation.emailRequired,
      password: en.auth.validation.passwordRequired,
    });
    expect(validateSignIn({ email: "ana@example.com", password: "short" }, t)).toEqual({});
  });
});

describe("firstErrorField", () => {
  it("follows the order the form shows its fields, not the error object's order", () => {
    expect(firstErrorField(SIGN_UP_FIELDS, { accept_disclaimer: "x", password: "y" })).toBe("password");
    expect(firstErrorField(SIGN_UP_FIELDS, {})).toBeUndefined();
  });
});

describe("problemToFormErrors", () => {
  it.each<[string, ApiError, { field?: string; message: string }]>([
    ["underage → birth date", apiError(422, { code: "underage" }), { field: "birth_date", message: en.auth.errors.underage }],
    [
      "disclaimer_required → disclaimer checkbox",
      apiError(422, { code: "disclaimer_required" }),
      { field: "accept_disclaimer", message: en.auth.validation.disclaimerRequired },
    ],
    ["email_taken → email", apiError(409, { code: "email_taken" }), { field: "email", message: en.auth.errors.emailTaken }],
  ])("maps %s with the i18n message", (_, error, { field, message }) => {
    expect(problemToFormErrors(error, SIGN_UP_FIELDS, t)).toEqual({ fields: { [field!]: message } });
  });

  it("puts each validation_error field message next to the matching field", () => {
    const error = apiError(422, {
      code: "validation_error",
      errors: [
        { field: "email", code: "invalid_format", message: "value is not a valid email address" },
        { field: "timezone", code: "invalid_choice", message: "Unknown time zone." },
      ],
    });
    expect(problemToFormErrors(error, SIGN_UP_FIELDS, t)).toEqual({
      fields: { email: "value is not a valid email address", timezone: "Unknown time zone." },
    });
  });

  it("adds a form message when a validation_error field is not on the form", () => {
    const error = apiError(422, {
      code: "validation_error",
      errors: [{ field: "nickname", code: "unknown_field", message: "Extra inputs are not permitted" }],
    });
    expect(problemToFormErrors(error, SIGN_UP_FIELDS, t)).toEqual({ fields: {}, form: en.auth.errors.invalidRequest });
  });

  it("shows one generic message for invalid_credentials, never tied to a field", () => {
    const error = apiError(401, { code: "invalid_credentials", detail: "Email or password is incorrect." });
    expect(problemToFormErrors(error, SIGN_IN_FIELDS, t)).toEqual({ fields: {}, form: en.auth.errors.invalidCredentials });
  });

  it("uses Retry-After for rate_limited", () => {
    expect(problemToFormErrors(apiError(429, { code: "rate_limited" }, 900), SIGN_IN_FIELDS, t)).toEqual({
      fields: {},
      form: "Too many attempts. Try again in 15 minutes.",
    });
  });

  it.each<[string, unknown, string]>([
    ["a network failure", new TypeError("Failed to fetch"), en.errors.network],
    ["a 500", apiError(500, { code: "internal_error" }), en.errors.unexpected],
    ["a non-problem body (proxy page)", apiError(502, "<html>"), en.errors.unexpected],
    ["another 4xx", apiError(400, { code: "bad_request" }), en.auth.errors.invalidRequest],
  ])("falls back to a form message for %s", (_, error, message) => {
    expect(problemToFormErrors(error, SIGN_UP_FIELDS, t)).toEqual({ fields: {}, form: message });
  });
});

describe("rateLimitedMessage", () => {
  it.each<[number | null, string]>([
    [null, en.auth.errors.rateLimited.later],
    [0, "Too many attempts. Try again in 1 second."],
    [1, "Too many attempts. Try again in 1 second."],
    [45, "Too many attempts. Try again in 45 seconds."],
    [60, "Too many attempts. Try again in 1 minute."],
    [61, "Too many attempts. Try again in 2 minutes."],
    [900, "Too many attempts. Try again in 15 minutes."],
  ])("Retry-After %s → %s", (seconds, message) => {
    expect(rateLimitedMessage(seconds, t)).toBe(message);
  });
});

describe("parseRetryAfter", () => {
  const now = Date.parse("2026-10-23T12:00:00Z");
  it.each<[string | null, number | null]>([
    [null, null],
    ["900", 900],
    [" 30 ", 30],
    ["Fri, 23 Oct 2026 12:01:30 GMT", 90],
    ["Fri, 23 Oct 2026 11:00:00 GMT", 0],
    ["soon", null],
    ["-5", null],
  ])("%s → %s", (header, seconds) => {
    expect(parseRetryAfter(header, now)).toBe(seconds);
  });
});
