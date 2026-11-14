import { useId } from "react";
import { useTranslation } from "react-i18next";

import { usePendingSuggestions } from "../../api/suggestions";
import type { UnitSystem } from "../../lib/units";
import { SuggestionCard } from "./SuggestionCard";

/** Pending suggestions for the athlete, with accept / edit / reject. Renders nothing when there are none. */
export function PendingSuggestions({
  id,
  athleteId,
  units,
  className = "",
  icon,
  description,
  emptyMessage,
}: {
  /** Anchor of the section, so the day checklist can link to it. */
  id?: string;
  athleteId: string;
  units: UnitSystem;
  className?: string;
  /** Decorative icon shown before the heading. */
  icon?: React.ReactNode;
  /** One or two sentences under the heading: what the section is and what to do with it. */
  description?: string;
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
    <section id={id} aria-labelledby={headingId} className={className}>
      <h2 id={headingId} className="flex items-center gap-2 font-display text-step-2 font-bold">
        {icon}
        {t("suggestions.title")}
      </h2>
      {description && (
        <p className="mt-1 text-step--1 text-slate" data-testid="section-description">
          {description}
        </p>
      )}
      {pending.data.length === 0 && <p className="mt-1 text-slate">{emptyMessage}</p>}
      <ul className="mt-1">
        {pending.data.map((suggestion) => (
          <SuggestionCard key={suggestion.id} suggestion={suggestion} units={units} />
        ))}
      </ul>
    </section>
  );
}
