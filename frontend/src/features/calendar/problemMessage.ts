import { isApiError } from "../../api/errors";

const MOVE_CODES = ["day_occupied", "session_finished", "outside_week", "date_in_past"] as const;

/** i18n key (under `calendar.move.errors`) for a failed move, from the stable problem code. */
export function moveErrorKey(error: unknown): (typeof MOVE_CODES)[number] | "generic" {
  if (isApiError(error)) {
    const code = MOVE_CODES.find((c) => c === error.problem.code);
    if (code) return code;
  }
  return "generic";
}
