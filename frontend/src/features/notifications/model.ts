import type { AppNotification, NotificationType } from "../../api/notifications";
import { paths } from "../../paths";

/** i18n key of the text of a type; types without text yet use the generic fallback. */
const TEXT_KEYS: Partial<Record<NotificationType, string>> = {
  progression_suggestion: "notifications.types.progression_suggestion",
  calorie_suggestion: "notifications.types.calorie_suggestion",
  recalc_prompt: "notifications.types.recalc_prompt",
  content_removed: "notifications.types.content_removed",
};

export function textKey(type: NotificationType) {
  return TEXT_KEYS[type] ?? "notifications.types.generic";
}

/** Where a notification leads; `null` when its type has no target yet (coach issues add theirs). */
export function targetOf(notification: AppNotification): string | null {
  switch (notification.type) {
    // Today lists every pending suggestion kind (spec section 5).
    case "progression_suggestion":
    case "calorie_suggestion":
    case "content_removed":
      return paths.today;
    // Only the Body page renders the recalculation prompt.
    case "recalc_prompt":
      return paths.body;
    default:
      return null;
  }
}

/** Types shown as banners on Today (D79.3). */
export const BANNER_TYPES: readonly NotificationType[] = [
  "progression_suggestion",
  "calorie_suggestion",
  "recalc_prompt",
  "content_removed",
];
export const MAX_BANNERS = 3;
