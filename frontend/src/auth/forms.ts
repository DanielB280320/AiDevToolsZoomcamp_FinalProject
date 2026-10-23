import type { TFunction } from "i18next";

import { isApiError } from "../api/errors";
import { UNKNOWN_PROBLEM_CODE } from "../api/problem";
import type { LogInRequest, SignUpRequest } from "../api/session";

export const SIGN_UP_FIELDS = [
  "email",
  "password",
  "display_name",
  "role",
  "birth_date",
  "units",
  "timezone",
  "accept_disclaimer",
] as const satisfies readonly (keyof SignUpRequest)[];
export type SignUpField = (typeof SIGN_UP_FIELDS)[number];

export const SIGN_IN_FIELDS = ["email", "password"] as const satisfies readonly (keyof LogInRequest)[];
export type SignInField = (typeof SIGN_IN_FIELDS)[number];

/** Limits from openapi.yaml (`SignUpRequest`, `LogInRequest`). */
export const PASSWORD_MIN_LENGTH = 10;
export const PASSWORD_MAX_LENGTH = 128;
export const DISPLAY_NAME_MAX_LENGTH = 60;
export const EMAIL_MAX_LENGTH = 254;

// Same rule as the backend: one `@`, no whitespace, a dot in the domain.
const EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

export interface FormErrors<F extends string> {
  fields: Partial<Record<F, string>>;
  /** A message about the whole form (not tied to one field). */
  form?: string;
}

/** The form's values as typed; the radios start empty so the choice is explicit. */
export interface SignUpValues {
  email: string;
  password: string;
  display_name: string;
  role: SignUpRequest["role"] | "";
  birth_date: string;
  units: SignUpRequest["units"] | "";
  timezone: string;
  accept_disclaimer: boolean;
}

export type SignInValues = Record<SignInField, string>;

function emailError(email: string, t: TFunction): string | undefined {
  const value = email.trim();
  if (!value) return t("auth.validation.emailRequired");
  if (!EMAIL_PATTERN.test(value) || value.length > EMAIL_MAX_LENGTH) return t("auth.validation.emailInvalid");
  return undefined;
}

function compact<F extends string>(fields: Partial<Record<F, string | undefined>>): Partial<Record<F, string>> {
  return Object.fromEntries(Object.entries(fields).filter(([, message]) => message)) as Partial<Record<F, string>>;
}

/** Mirrors the `SignUpRequest` contract so most mistakes never reach the API. */
export function validateSignUp(values: SignUpValues, t: TFunction): Partial<Record<SignUpField, string>> {
  return compact<SignUpField>({
    email: emailError(values.email, t),
    password: !values.password
      ? t("auth.validation.passwordRequired")
      : values.password.length < PASSWORD_MIN_LENGTH
        ? t("auth.validation.passwordTooShort", { count: PASSWORD_MIN_LENGTH })
        : values.password.length > PASSWORD_MAX_LENGTH
          ? t("auth.validation.passwordTooLong", { count: PASSWORD_MAX_LENGTH })
          : undefined,
    display_name: !values.display_name.trim()
      ? t("auth.validation.displayNameRequired")
      : values.display_name.trim().length > DISPLAY_NAME_MAX_LENGTH
        ? t("auth.validation.displayNameTooLong", { count: DISPLAY_NAME_MAX_LENGTH })
        : undefined,
    role: values.role ? undefined : t("auth.validation.roleRequired"),
    birth_date: /^\d{4}-\d{2}-\d{2}$/.test(values.birth_date) ? undefined : t("auth.validation.birthDateRequired"),
    units: values.units ? undefined : t("auth.validation.unitsRequired"),
    timezone: values.timezone ? undefined : t("auth.validation.timezoneRequired"),
    accept_disclaimer: values.accept_disclaimer ? undefined : t("auth.validation.disclaimerRequired"),
  });
}

/** Mirrors the `LogInRequest` contract. */
export function validateSignIn(values: SignInValues, t: TFunction): Partial<Record<SignInField, string>> {
  return compact<SignInField>({
    email: emailError(values.email, t),
    password: values.password ? undefined : t("auth.validation.passwordRequired"),
  });
}

/** "Try again in N seconds/minutes" from `Retry-After`; "try again later" when it is unknown. */
export function rateLimitedMessage(retryAfterSeconds: number | null, t: TFunction): string {
  if (retryAfterSeconds === null) return t("auth.errors.rateLimited.later");
  if (retryAfterSeconds < 60) {
    return t("auth.errors.rateLimited.seconds", { count: Math.max(1, retryAfterSeconds) });
  }
  return t("auth.errors.rateLimited.minutes", { count: Math.ceil(retryAfterSeconds / 60) });
}

/**
 * Maps a failed sign-up or sign-in to messages. Known problem codes get a specific message from
 * the i18n file, shown next to their field when the form has it; `validation_error` shows each
 * API field message next to the matching field.
 */
export function problemToFormErrors<F extends string>(
  error: unknown,
  fields: readonly F[],
  t: TFunction,
): FormErrors<F> {
  if (!isApiError(error)) return { fields: {}, form: t("errors.network") };

  const has = (field: string): field is F => (fields as readonly string[]).includes(field);
  const onField = (field: string, message: string): FormErrors<F> =>
    has(field) ? { fields: { [field]: message } as Partial<Record<F, string>> } : { fields: {}, form: message };

  const { code, fieldErrors } = error.problem;
  switch (code) {
    case "underage":
      return onField("birth_date", t("auth.errors.underage"));
    case "disclaimer_required":
      return onField("accept_disclaimer", t("auth.validation.disclaimerRequired"));
    case "email_taken":
      return onField("email", t("auth.errors.emailTaken"));
    case "invalid_credentials":
      return { fields: {}, form: t("auth.errors.invalidCredentials") };
    case "rate_limited":
      return { fields: {}, form: rateLimitedMessage(error.retryAfterSeconds, t) };
    case "validation_error": {
      const matched: Partial<Record<F, string>> = {};
      let unmatched = false;
      for (const [field, message] of Object.entries(fieldErrors)) {
        if (has(field)) matched[field] = message;
        else unmatched = true;
      }
      const none = Object.keys(matched).length === 0;
      return unmatched || none ? { fields: matched, form: t("auth.errors.invalidRequest") } : { fields: matched };
    }
    default:
      // Other 4xx (e.g. `bad_request`) mean the request itself was refused; 5xx or a non-problem
      // body (proxy error page) is a server-side failure.
      return error.status < 500 && code !== UNKNOWN_PROBLEM_CODE
        ? { fields: {}, form: t("auth.errors.invalidRequest") }
        : { fields: {}, form: t("errors.unexpected") };
  }
}

/** The first field with an error, in the order the form shows them. */
export function firstErrorField<F extends string>(fields: readonly F[], errors: Partial<Record<F, string>>): F | undefined {
  return fields.find((field) => errors[field]);
}
