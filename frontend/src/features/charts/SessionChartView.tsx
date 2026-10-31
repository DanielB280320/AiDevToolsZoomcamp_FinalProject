import { useTranslation } from "react-i18next";
import { Bar, BarChart, CartesianGrid, Legend, XAxis, YAxis } from "recharts";

import { type SessionChart, type SessionChartExercise, useSessionChart } from "../../api/charts";
import { DAY_FORMAT, formatDay } from "../../lib/calendarDates";
import { weightUnit, type UnitSystem } from "../../lib/units";
import { ChartBox } from "./ChartBox";
import { CHART_COLORS, displayWeight, percent, setBars, setMeasure, STATUS_MARKER } from "./chartData";
import { ChartState } from "./ChartState";

const STATUS_COLOR = {
  met: "text-spruce",
  partial: "text-iron",
  missed: "text-alert",
  skipped: "text-slate",
  extra: "text-slate",
} as const;

function ExerciseSets({ entry, units }: { entry: SessionChartExercise; units: UnitSystem }) {
  const { t } = useTranslation();
  const measure = setMeasure(entry.sets);
  const bars = setBars(entry.sets, measure);
  const completion = percent(entry.completion);
  const unit = weightUnit(units);

  return (
    <section aria-labelledby={`ex-${entry.exercise.id}`} className="mt-6 min-w-0" data-testid="session-exercise">
      <h3 id={`ex-${entry.exercise.id}`} className="font-display text-step-1 font-bold">
        {entry.exercise.name}
        {entry.is_extra && <span className="ml-2 text-step--1 font-semibold text-slate">{t("charts.session.extra")}</span>}
        {completion !== null && <span className="ml-2 text-step--1 font-semibold text-slate">{t("charts.percent", { value: completion })}</span>}
      </h3>
      <ChartBox label={t("charts.session.chartLabel", { name: entry.exercise.name })} height={180}>
        <BarChart data={bars} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
          <CartesianGrid stroke={CHART_COLORS.line} vertical={false} />
          <XAxis dataKey="set_no" tickFormatter={(n: number) => t("charts.session.setShort", { n })} />
          <YAxis allowDecimals={false} />
          <Legend />
          <Bar dataKey="target" name={t("charts.session.target")} fill={CHART_COLORS.target} isAnimationActive={false} />
          <Bar dataKey="actual" name={t("charts.session.actual")} fill={CHART_COLORS.actual} isAnimationActive={false} />
        </BarChart>
      </ChartBox>
      <ol className="mt-2">
        {entry.sets.map((s) => {
          const weight = displayWeight(s.weight_kg, units);
          const targetWeight = displayWeight(s.target_weight_kg, units);
          const pct = percent(s.completion);
          return (
            <li
              key={s.set_no}
              data-testid="set-row"
              data-status={s.status}
              className="flex flex-wrap items-baseline gap-x-3 border-b border-line py-1.5"
            >
              <span aria-hidden="true" className={`w-5 text-center font-bold ${STATUS_COLOR[s.status]}`}>
                {STATUS_MARKER[s.status]}
              </span>
              <span className="font-semibold">{t("charts.session.set", { n: s.set_no })}</span>
              <span className={STATUS_COLOR[s.status]}>{t(`charts.session.status.${s.status}`)}</span>
              <span className="text-step--1 text-slate">
                {measure === "reps"
                  ? t("charts.session.repsOf", { actual: s.reps ?? "-", target: s.target_reps ?? "-" })
                  : t("charts.session.secondsOf", { actual: s.seconds ?? "-", target: s.target_seconds ?? "-" })}
                {(weight !== null || targetWeight !== null) &&
                  ` · ${t("charts.session.weightOf", { actual: weight ?? "-", target: targetWeight ?? "-", unit })}`}
              </span>
              {pct !== null && <span className="ml-auto text-step--1 font-semibold">{t("charts.percent", { value: pct })}</span>}
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function SessionBody({ data, units }: { data: SessionChart; units: UnitSystem }) {
  const { t, i18n } = useTranslation();
  const completion = percent(data.completion);
  return (
    <div>
      <p className="text-slate">
        {data.training_day_name} · {formatDay(data.date, i18n.language, DAY_FORMAT.weekdayDayMonth)}
        {completion !== null && ` · ${t("charts.session.completion", { value: completion })}`}
        {data.kcal !== null && ` · ${t("charts.session.kcal", { value: data.kcal })}`}
      </p>
      {data.exercises.map((e) => (
        <ExerciseSets key={e.exercise.id} entry={e} units={units} />
      ))}
    </div>
  );
}

/** Session view (F15.2): per set, planned target vs. what was done, with the API's set status. */
export function SessionChartView({ athleteId, sessionId, units }: { athleteId: string; sessionId: string; units: UnitSystem }) {
  const { t } = useTranslation();
  const query = useSessionChart(athleteId, sessionId);
  return (
    <ChartState query={query} isEmpty={(d) => d.exercises.length === 0} emptyMessage={t("charts.session.empty")}>
      {(data) => <SessionBody data={data} units={units} />}
    </ChartState>
  );
}
