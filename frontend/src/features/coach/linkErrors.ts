import { isApiError } from "../../api/errors";

export type LinkErrorKey = "linkExists" | "notPending" | "notFound" | "generic";

/** Maps a failed link call to its message key; the 409 codes are the ones a user can act on. */
export function linkErrorKey(error: unknown): LinkErrorKey {
  if (isApiError(error)) {
    if (error.problem.code === "link_exists") return "linkExists";
    if (error.problem.code === "link_not_pending") return "notPending";
    if (error.status === 404) return "notFound";
  }
  return "generic";
}
