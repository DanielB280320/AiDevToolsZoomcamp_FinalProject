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
