import { useTranslation } from "react-i18next";

import type { UnitSystem } from "../../lib/units";
import { AdherenceView } from "./AdherenceView";
import { BodyChartView } from "./BodyChartView";
import { ExerciseChartView } from "./ExerciseChartView";
import { WeeklySummaryView } from "./WeeklySummaryView";

/** The four progress sections (spec F15): weekly summary, adherence heat map, exercise and body charts. */
export function ProgressView({
  athleteId,
  units,
  today,
}: {
  athleteId: string;
  units: UnitSystem;
  today: string;
}) {
  const { t } = useTranslation();
  const sections = [
    { key: "weekly", body: <WeeklySummaryView athleteId={athleteId} units={units} today={today} /> },
    { key: "adherence", body: <AdherenceView athleteId={athleteId} today={today} /> },
    { key: "exercise", body: <ExerciseChartView athleteId={athleteId} units={units} /> },
    { key: "body", body: <BodyChartView athleteId={athleteId} units={units} /> },
  ] as const;
  return (
    <>
      {sections.map(({ key, body }) => (
        <section key={key} aria-labelledby={`progress-${key}`} className="mt-8 min-w-0 border-t-4 border-iron pt-3">
          <h2 id={`progress-${key}`} className="font-display text-step-2 font-bold">
            {t(`charts.sections.${key}`)}
          </h2>
          <div className="mt-3 min-w-0">{body}</div>
        </section>
      ))}
    </>
  );
}
