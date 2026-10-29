import { useId } from "react";
import { useTranslation } from "react-i18next";

import { usePendingSuggestions } from "../../api/suggestions";
import type { UnitSystem } from "../../lib/units";
import { SuggestionCard } from "./SuggestionCard";

/** Pending suggestions for the athlete, with accept / edit / reject. Renders nothing when there are none. */
export function PendingSuggestions({
  athleteId,
  units,
  className = "",
  emptyMessage,
}: {
  athleteId: string;
  units: UnitSystem;
  className?: string;
  /** Shown under the heading when nothing is pending; without it the section is hidden. */
  emptyMessage?: string;
}) {
  const { t } = useTranslation();
  const headingId = useId();
  const pending = usePendingSuggestions(athleteId);
  if (pending.isError) {
    return (
      <p role="alert" className="mt-2 text-alert">
        {t("suggestions.loadFailed")}
      </p>
    );
  }
  if (!pending.data || (pending.data.length === 0 && !emptyMessage)) return null;
  return (
    <section aria-labelledby={headingId} className={className}>
      <h2 id={headingId} className="font-display text-step-2 font-bold">
        {t("suggestions.title")}
      </h2>
      {pending.data.length === 0 && <p className="mt-1 text-slate">{emptyMessage}</p>}
      <ul className="mt-1">
        {pending.data.map((suggestion) => (
          <SuggestionCard key={suggestion.id} suggestion={suggestion} units={units} />
        ))}
      </ul>
    </section>
  );
}
