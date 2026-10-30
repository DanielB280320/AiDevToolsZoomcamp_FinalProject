import { useTranslation } from "react-i18next";
import { Navigate } from "react-router";

import { useSignedInUser } from "../components/RequireAuth";
import { AdherenceView } from "../features/charts/AdherenceView";
import { BodyChartView } from "../features/charts/BodyChartView";
import { ExerciseChartView } from "../features/charts/ExerciseChartView";
import { WeeklySummaryView } from "../features/charts/WeeklySummaryView";
import { CalendarNav } from "../features/calendar/CalendarNav";
import { localDay } from "../lib/today";
import { paths } from "../paths";

/** Progress charts (spec F15). Owner-only until coach linking (#47, D76(8)). */
export function ProgressPage() {
  const { t, i18n } = useTranslation();
  const me = useSignedInUser();
  if (me.role === "athlete" && !me.onboarding_completed) return <Navigate to={paths.onboarding} replace />;
  const today = localDay(new Date(), me.timezone, i18n.language).isoDate;

  const sections = [
    { key: "weekly", body: <WeeklySummaryView athleteId={me.id} units={me.units} today={today} /> },
    { key: "adherence", body: <AdherenceView athleteId={me.id} today={today} /> },
    { key: "exercise", body: <ExerciseChartView athleteId={me.id} units={me.units} /> },
    { key: "body", body: <BodyChartView athleteId={me.id} units={me.units} /> },
  ] as const;

  return (
    <article className="min-w-0 max-w-[40rem]">
      {me.role === "athlete" && <CalendarNav />}
      <h1 className="font-display text-step-4 font-bold">{t("charts.title")}</h1>
      {me.role === "coach" ? (
        <p className="mt-6 border-l-4 border-iron pl-3">{t("charts.coachNotice")}</p>
      ) : (
        sections.map(({ key, body }) => (
          <section key={key} aria-labelledby={`progress-${key}`} className="mt-8 min-w-0 border-t-4 border-iron pt-3">
            <h2 id={`progress-${key}`} className="font-display text-step-2 font-bold">
              {t(`charts.sections.${key}`)}
            </h2>
            <div className="mt-3 min-w-0">{body}</div>
          </section>
        ))
      )}
    </article>
  );
}
