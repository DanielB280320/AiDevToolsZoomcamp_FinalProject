import { useTranslation } from "react-i18next";

import type { CalendarDay } from "../../api/calendar";
import { percent } from "../charts/chartData";
import { monthKpis } from "./monthKpis";
import { Tile } from "./ProgressKpis";

/**
 * The month in figures (D103): workouts done of planned, average completion, workouts missed,
 * planned meals eaten and the average estimated calories eaten, all up to today. Derived from the
 * calendar days the grid already loaded; a figure without data shows a dash.
 */
export function MonthKpis({ days, today, title }: { days: CalendarDay[]; today: string; title: string }) {
  const { t } = useTranslation();
  const kpis = monthKpis(days, today);
  const dash = t("charts.none");
  const completion = percent(kpis.avgCompletion);
  const meals = percent(kpis.mealsRatio);
  const started = days.some((d) => d.date <= today);
  const inProgress = started && days.some((d) => d.date > today);
  return (
    <section aria-labelledby="month-kpis" className="mb-6" data-testid="month-kpis">
      <h2 id="month-kpis" className="font-display text-step-1 font-bold">
        {title}
      </h2>
      <p className="text-step--1 text-slate">
        {t(!started ? "calendar.month.kpis.future" : inProgress ? "calendar.month.kpis.soFar" : "calendar.month.kpis.whole")}
      </p>
      <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3">
        <Tile
          id="month-workouts"
          label={t("calendar.month.kpis.workouts")}
          value={kpis.sessionsPlanned > 0 ? t("calendar.month.kpis.ofValue", { done: kpis.sessionsDone, planned: kpis.sessionsPlanned }) : dash}
          hint={kpis.sessionsUpcoming > 0 ? t("calendar.month.kpis.upcoming", { count: kpis.sessionsUpcoming }) : undefined}
        />
        <Tile
          id="month-completion"
          label={t("calendar.month.kpis.completion")}
          value={completion === null ? dash : t("charts.percent", { value: completion })}
          hint={t("calendar.month.kpis.completionHint")}
        />
        <Tile id="month-missed" label={t("calendar.month.kpis.missed")} value={started ? String(kpis.sessionsMissed) : dash} />
        <Tile
          id="month-meals"
          label={t("calendar.month.kpis.meals")}
          value={meals === null ? dash : t("charts.percent", { value: meals })}
          hint={meals === null ? undefined : t("calendar.month.kpis.ofValue", { done: kpis.mealsEaten, planned: kpis.mealsPlanned })}
        />
        <Tile
          id="month-kcal"
          label={t("calendar.month.kpis.kcal")}
          value={kpis.avgEatenKcal === null ? dash : t("calendar.month.kpis.kcalValue", { value: kpis.avgEatenKcal })}
          hint={t("calendar.month.kpis.kcalHint", { count: kpis.daysWithMeals })}
        />
      </dl>
    </section>
  );
}
