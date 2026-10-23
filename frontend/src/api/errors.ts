import { type ProblemDetails, toProblemDetails } from "./problem";

/** A non-2xx API response, mapped to what the UI needs. */
export class ApiError extends Error {
  readonly status: number;
  readonly problem: ProblemDetails;
  /** Seconds from the `Retry-After` header (429), or `null` when absent or unreadable. */
  readonly retryAfterSeconds: number | null;

  constructor(status: number, problem: ProblemDetails, retryAfterSeconds: number | null = null) {
    // The message carries only the status and stable code: never user input or health data.
    super(`API request failed: ${status} ${problem.code}`);
    this.name = "ApiError";
    this.status = status;
    this.problem = problem;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

/** Builds an `ApiError` from an openapi-fetch result (`error` is the parsed problem body). */
export function apiError(response: Response, body: unknown): ApiError {
  return new ApiError(
    response.status,
    toProblemDetails(body),
    parseRetryAfter(response.headers.get("Retry-After")),
  );
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}

/**
 * `Retry-After` is either delay-seconds or an HTTP-date (RFC 9110 §10.2.3).
 * Returns whole seconds to wait (≥ 0), or `null` when the header is missing or invalid.
 */
export function parseRetryAfter(value: string | null, now: number = Date.now()): number | null {
  if (value === null) return null;
  const trimmed = value.trim();
  if (/^\d+$/.test(trimmed)) return Number(trimmed);
  // An HTTP-date always names a weekday or month; without letters it is a malformed delay
  // (e.g. "-5"), which Date.parse would otherwise read as a year.
  if (!/[a-z]/i.test(trimmed)) return null;
  const at = Date.parse(trimmed);
  if (Number.isNaN(at)) return null;
  return Math.max(0, Math.ceil((at - now) / 1000));
}
