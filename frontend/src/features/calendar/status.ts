import type { CalendarDay, TrainingStatus } from "../../api/calendar";

/** What a day's training badge shows (spec F9: done / partial / missed / rest, plus not started). */
export type BadgeKind = "done" | "partial" | "missed" | "rest" | "planned";

/**
 * Maps the API status to the badge. `partial` = work was logged but the plan wasn't completed:
 * a session still in progress, or a finished one below 100 % completion (F10.2).
 */
export function badgeKind(status: TrainingStatus, completion: number | null): BadgeKind {
  switch (status) {
    case "rest":
      return "rest";
    case "missed":
      return "missed";
    case "in_progress":
      return "partial";
    case "done":
      return completion !== null && completion < 1 ? "partial" : "done";
    case "planned":
      return "planned";
  }
}

export const dayBadge = (day: CalendarDay) => badgeKind(day.training_status, day.training_completion);

/** Why a day carries its badge, as a translation key under `calendar.week.reason` (D102). */
export type StatusReason =
  | { key: "done" | "doneNoFigure" | "partialInProgress" | "missed" | "rest" | "planned" }
  | { key: "partialFinished"; value: number };

/**
 * Explains the badge of `badgeKind` from the same two inputs: the status and, for a finished
 * session, its completion (F10.2). The percent is rounded down so a partial day never reads 100 %.
 */
export function statusReason(status: TrainingStatus, completion: number | null): StatusReason {
  switch (status) {
    case "rest":
      return { key: "rest" };
    case "missed":
      return { key: "missed" };
    case "in_progress":
      return { key: "partialInProgress" };
    case "planned":
      return { key: "planned" };
    case "done":
      if (completion === null) return { key: "doneNoFigure" };
      if (completion >= 1) return { key: "done" };
      return { key: "partialFinished", value: Math.max(0, Math.floor(completion * 100)) };
  }
}
