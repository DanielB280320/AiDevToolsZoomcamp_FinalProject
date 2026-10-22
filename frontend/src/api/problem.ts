import type { components } from "./schema";

type Problem = components["schemas"]["Problem"];

/** What the UI needs from an RFC 9457 problem response (openapi.yaml `Problem`). */
export interface ProblemDetails {
  /** Stable machine-readable code, e.g. `validation_error`. */
  code: string;
  /** Human-readable message that is safe to show. */
  detail: string;
  /** First message per offending field, keyed by the field path from the API. */
  fieldErrors: Record<string, string>;
}

/** Used when the response is not a problem document (proxy error page, network HTML, …). */
export const UNKNOWN_PROBLEM_CODE = "unexpected_response";

const PROBLEM_CONTENT_TYPE = "application/problem+json";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isProblem(value: unknown): value is Problem {
  return isRecord(value) && typeof value.code === "string";
}

/**
 * Maps a parsed problem body to `{code, detail, fieldErrors}`.
 * Anything that is not a problem document maps to `UNKNOWN_PROBLEM_CODE` with an empty detail,
 * so callers can fall back to a generic, translated message.
 */
export function toProblemDetails(body: unknown): ProblemDetails {
  if (!isProblem(body)) {
    return { code: UNKNOWN_PROBLEM_CODE, detail: "", fieldErrors: {} };
  }

  const fieldErrors: Record<string, string> = {};
  for (const error of Array.isArray(body.errors) ? body.errors : []) {
    if (!isRecord(error) || typeof error.field !== "string" || typeof error.message !== "string") {
      continue;
    }
    if (!(error.field in fieldErrors)) {
      fieldErrors[error.field] = error.message;
    }
  }

  const detail =
    typeof body.detail === "string" ? body.detail : typeof body.title === "string" ? body.title : "";

  return { code: body.code, detail, fieldErrors };
}

/** Reads a fetch `Response` and maps it with `toProblemDetails`. Never throws. */
export async function problemFromResponse(response: Response): Promise<ProblemDetails> {
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.toLowerCase().startsWith(PROBLEM_CONTENT_TYPE)) {
    return toProblemDetails(undefined);
  }
  try {
    return toProblemDetails(await response.json());
  } catch {
    return toProblemDetails(undefined);
  }
}
