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
 * decided (D98). Hidden when empty. With `day` it lists the decisions made on that day instead
 * (the Month view's day detail, D103) and says so when there were none.
 */
export function DecidedSuggestions({
  athleteId,
  timezone,
  className = "",
  icon,
  description,
  day,
}: {
  athleteId: string;
  units?: UnitSystem;
  /** The athlete's time zone for the decision dates; the browser's zone when omitted. */
  timezone?: string;
  className?: string;
  /** Decorative icon shown before the heading. */
  icon?: React.ReactNode;
  /** One or two sentences under the heading: what the section is and what to do with it. */
  description?: string;
  /** Only the decisions made on this day (`YYYY-MM-DD` in `timezone`), under a smaller heading. */
  day?: string;
}) {
  const { t, i18n } = useTranslation();
  const dateOf = (iso: string) => new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium", timeZone: timezone }).format(new Date(iso));
  // en-CA formats a date as YYYY-MM-DD: the calendar day of the decision in the athlete's zone.
  const isoDayOf = (iso: string) =>
    new Intl.DateTimeFormat("en-CA", { timeZone: timezone, year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(iso));
  const headingId = useId();
  const decided = useDecidedSuggestions(athleteId, day !== undefined);
  if (!decided.data) return null;
  const items =
    day === undefined
      ? decided.data
      : decided.data.filter((s) => s.decided_at && isoDayOf(s.decided_at) === day);
  if (items.length === 0 && day === undefined) return null;
  const Heading = day === undefined ? "h2" : "h3";
  return (
    <section aria-labelledby={headingId} className={className}>
      <Heading id={headingId} className={`flex items-center gap-2 font-display font-bold ${day === undefined ? "text-step-2" : "text-step-1"}`}>
        {icon}
        {t(day === undefined ? "suggestions.decided.title" : "suggestions.decided.dayTitle")}
      </Heading>
      {description && (
        <p className="mt-1 text-step--1 text-slate" data-testid="section-description">
          {description}
        </p>
      )}
      {items.length === 0 && <p className="mt-1 text-slate">{t("suggestions.decided.dayEmpty")}</p>}
      <ul className="mt-1">
        {items.map((s) => {
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
