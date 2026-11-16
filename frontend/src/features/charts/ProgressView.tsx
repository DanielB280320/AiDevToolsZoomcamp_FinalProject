import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router";

import type { UnitSystem } from "../../lib/units";
import { AdherenceView } from "./AdherenceView";
import { BodyChartView } from "./BodyChartView";
import { ExerciseChartView } from "./ExerciseChartView";
import { paramsFromPeriod, periodFromParams, type Period } from "./period";
import { PeriodOverview } from "./PeriodOverview";
import { PeriodSelector } from "./PeriodSelector";
import { PeriodTimelines } from "./PeriodTimelines";
import { CARD } from "../../components/card";

const SECTIONS = ["overview", "timelines", "adherence", "exercise", "body"] as const;

/**
 * The Progress page body (spec F15.6-F15.10, D109): a description, one period selector kept in the
 * URL, and sections that all follow it. The linked coach's client view uses the same component
 * with the descriptions worded for the coach (`audience`).
 */
export function ProgressView({
  athleteId,
  units,
  today,
  audience = "athlete",
}: {
  athleteId: string;
  units: UnitSystem;
  today: string;
  audience?: "athlete" | "coach";
}) {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const period = periodFromParams(params, today);
  const { from, to } = period;
  const help = audience === "coach" ? "charts.helpCoach" : "charts.help";

  const choose = (next: Period) => setParams(paramsFromPeriod(next), { replace: true });

  const bodies = {
    overview: <PeriodOverview athleteId={athleteId} units={units} from={from} to={to} />,
    timelines: <PeriodTimelines athleteId={athleteId} units={units} from={from} to={to} />,
    adherence: <AdherenceView athleteId={athleteId} from={from} to={to} />,
    exercise: <ExerciseChartView athleteId={athleteId} units={units} from={from} to={to} />,
    body: <BodyChartView athleteId={athleteId} units={units} from={from} to={to} />,
  } as const;

  return (
    <>
      <p className="mt-2 max-w-[38rem] text-step--1 text-slate" data-testid="progress-description">
        {t(audience === "coach" ? "charts.descriptionCoach" : "charts.description")}
      </p>
      <PeriodSelector period={period} today={today} onChange={choose} />
      {SECTIONS.map((key) => (
        <section key={key} aria-labelledby={`progress-${key}`} className={`mt-8 ${CARD}`}>
          <h2 id={`progress-${key}`} className="font-display text-step-1 font-semibold">
            {t(`charts.sections.${key}`)}
          </h2>
          <p className="mt-1 max-w-[38rem] text-step--1 text-slate" data-testid={`help-${key}`}>
            {t(`${help}.${key}`)}
          </p>
          <div className="mt-3 min-w-0">{bodies[key]}</div>
        </section>
      ))}
    </>
  );
}
