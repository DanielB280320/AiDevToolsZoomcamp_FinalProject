import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import type { DayView } from "../../api/calendar";
import { useAdherenceChart, useBodyChart, useWeeklySummary } from "../../api/charts";
import { addDays, DAY_FORMAT, formatDay, mondayOf } from "../../lib/calendarDates";
import { weightUnit, type UnitSystem } from "../../lib/units";
import { displayWeight, percent } from "../charts/chartData";

/** The longest range the body chart offers; "to date" figures look back this far (D100). */
const LOOKBACK_WEEKS = 52;
const LOOKBACK_DAYS = LOOKBACK_WEEKS * 7;

function Tile({ id, label, value, hint }: { id: string; label: string; value: string; hint?: string }) {
  return (
    <div data-testid={`kpi-${id}`} className="min-w-0 border-t-4 border-iron pt-2">
      <dt className="text-step--1 font-semibold uppercase tracking-wide text-slate">{label}</dt>
      <dd className="m-0">
        <span className="block font-display text-step-3 font-bold leading-none">{value}</span>
        {hint && <span className="block text-step--1 text-slate">{hint}</span>}
      </dd>
    </div>
  );
}

/**
 * Progress at a glance on Today (F9.5, D100): this week's workouts and completion, workouts
 * completed and weight change over the last 12 months, and the records set in the day's workout.
 * Read from the chart endpoints of the Progress page; a figure without data shows a dash.
 */
export function ProgressKpis({
  day,
  athleteId,
  units,
  progressLink,
}: {
  day: DayView;
  athleteId: string;
  units: UnitSystem;
  /** Where "See all progress" leads; left out when there is no such page for the reader. */
  progressLink?: string;
}) {
  const { t, i18n } = useTranslation();
  const week = useWeeklySummary(athleteId, mondayOf(day.date)).data;
  const year = useAdherenceChart(athleteId, addDays(day.date, -(LOOKBACK_DAYS - 1)), day.date).data;
  const body = useBodyChart(athleteId, LOOKBACK_WEEKS).data;
  const dash = t("charts.none");

  const completion = week ? percent(week.avg_completion) : null;
  const workouts = year ? year.weeks.reduce((sum, w) => sum + w.sessions_done, 0) : null;

  const weighed = (body?.points ?? []).filter((p) => (p.weight_avg_7d_kg ?? p.weight_kg) !== null);
  const first = weighed[0];
  const last = weighed[weighed.length - 1];
  const weightOf = (p: (typeof weighed)[number]) => displayWeight(p.weight_avg_7d_kg ?? p.weight_kg, units) ?? 0;
  const change = first && last && first !== last ? Math.round((weightOf(last) - weightOf(first)) * 10) / 10 : null;

  const records = day.session ? day.session.exercises.filter((e) => e.is_pr).length : null;

  return (
    <div className="mt-4" data-testid="progress-kpis">
      <h3 className="font-display text-step-1 font-bold">{t("calendar.today.kpis.title")}</h3>
      <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3">
        <Tile
          id="week"
          label={t("calendar.today.kpis.week")}
          value={week ? t("calendar.today.kpis.weekValue", { done: week.sessions_done, planned: week.sessions_planned }) : dash}
        />
        <Tile
          id="completion"
          label={t("calendar.today.kpis.completion")}
          value={completion === null ? dash : t("charts.percent", { value: completion })}
        />
        <Tile id="workouts" label={t("calendar.today.kpis.workouts")} value={workouts === null ? dash : String(workouts)} hint={t("calendar.today.kpis.lookback")} />
        <Tile
          id="weight"
          label={t("calendar.today.kpis.weight")}
          value={
            change === null
              ? dash
              : t(change > 0 ? "calendar.today.kpis.weightUp" : change < 0 ? "calendar.today.kpis.weightDown" : "calendar.today.kpis.weightSame", {
                  value: Math.abs(change),
                  unit: weightUnit(units),
                })
          }
          hint={change === null || !first ? t("calendar.today.kpis.weightNone") : t("calendar.today.kpis.since", { date: formatDay(first.date, i18n.language, DAY_FORMAT.dayMonth) })}
        />
        {records !== null && <Tile id="records" label={t("calendar.today.kpis.records")} value={String(records)} hint={t("calendar.today.kpis.recordsHint")} />}
      </dl>
      {progressLink && (
        <Link to={progressLink} className="mt-2 inline-flex min-h-11 items-center font-semibold text-spruce underline underline-offset-4">
          {t("calendar.today.kpis.more")}
        </Link>
      )}
    </div>
  );
}
