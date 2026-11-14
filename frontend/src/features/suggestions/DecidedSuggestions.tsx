import { useId } from "react";
import { useTranslation } from "react-i18next";

import { type Suggestion, useDecidedSuggestions } from "../../api/suggestions";
import type { UnitSystem } from "../../lib/units";

function titleOf(t: (key: string) => string, suggestion: Suggestion): string {
  if (suggestion.kind === "progression") return suggestion.payload.exercise.name;
  return t(`suggestions.kind.${suggestion.kind}`);
}

/**
 * The latest decided suggestions with who decided them (F11, F16): "Accepted by <coach>" when a
 * coach decided, plain "Accepted" / "Rejected" for the athlete's own decisions, each with the date it was
 * decided (D98). Hidden when empty.
 */
export function DecidedSuggestions({
  athleteId,
  timezone,
  className = "",
}: {
  athleteId: string;
  units?: UnitSystem;
  /** The athlete's time zone for the decision dates; the browser's zone when omitted. */
  timezone?: string;
  className?: string;
}) {
  const { t, i18n } = useTranslation();
  const dateOf = (iso: string) => new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium", timeZone: timezone }).format(new Date(iso));
  const headingId = useId();
  const decided = useDecidedSuggestions(athleteId);
  if (!decided.data || decided.data.length === 0) return null;
  return (
    <section aria-labelledby={headingId} className={className}>
      <h2 id={headingId} className="font-display text-step-2 font-bold">
        {t("suggestions.decided.title")}
      </h2>
      <ul className="mt-1">
        {decided.data.map((s) => {
          const by = s.decided_by?.role === "coach" ? s.decided_by.display_name : null;
          return (
            <li key={s.id} data-testid="decided-suggestion" className="border-b border-line py-2">
              <p className="font-semibold">{titleOf(t as (key: string) => string, s)}</p>
              <p className="text-step--1 text-slate">
                {s.status === "accepted"
                  ? by
                    ? t("suggestions.decided.acceptedBy", { name: by })
                    : t("suggestions.decided.accepted")
                  : by
                    ? t("suggestions.decided.rejectedBy", { name: by })
                    : t("suggestions.decided.rejected")}
                {s.decided_at && (
                  <>
                    {" · "}
                    <time dateTime={s.decided_at}>{dateOf(s.decided_at)}</time>
                  </>
                )}
              </p>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
