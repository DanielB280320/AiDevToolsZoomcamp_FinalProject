import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Line, LineChart, YAxis } from "recharts";

import { type DatedValueSeries, type WeeklySummary, useWeeklySummary } from "../../api/charts";
import { addDays, DAY_FORMAT, formatDay, mondayOf } from "../../lib/calendarDates";
import { weightUnit, type UnitSystem } from "../../lib/units";
import { ChartBox } from "./ChartBox";
import { AUTO_DOMAIN, CHART_COLORS, displayWeight, percent } from "./chartData";
import { ChartState } from "./ChartState";

function Sparkline({ series, label }: { series: DatedValueSeries; label: string }) {
  const { t } = useTranslation();
  if (!series.some((p) => p.value !== null)) {
    return <p className="mt-2 text-step--1 text-slate">{t("charts.weekly.noTrend")}</p>;
  }
  return (
    <div className="mt-2">
      <ChartBox label={label} height={48}>
        <LineChart data={series} margin={{ top: 4, right: 4, bottom: 4, left: 4 }}>
          <YAxis hide domain={AUTO_DOMAIN} />
          <Line dataKey="value" stroke={CHART_COLORS.actual} strokeWidth={2} dot={false} isAnimationActive={false} />
        </LineChart>
      </ChartBox>
    </div>
  );
}

function Tile({ title, tag, children, testId }: { title: string; tag?: string; children: ReactNode; testId: string }) {
  return (
    <section data-testid={testId} className="min-w-0 border-t-4 border-iron bg-chalk pt-2">
      <h3 className="flex flex-wrap items-baseline gap-x-2 text-step--1 font-semibold uppercase tracking-wide text-slate">
        {title}
        {tag && <span className="rounded-sm bg-plate px-1.5 text-iron normal-case">{tag}</span>}
      </h3>
      {children}
    </section>
  );
}

const VALUE = "font-display text-step-3 font-bold leading-none";

function SummaryBody({ data, units }: { data: WeeklySummary; units: UnitSystem }) {
  const { t } = useTranslation();
  const unit = weightUnit(units);
  const estimated = t("charts.estimated");
  const completion = percent(data.avg_completion);
  const start = displayWeight(data.weight_avg_start_kg, units);
  const end = displayWeight(data.weight_avg_end_kg, units);
  const dash = t("charts.none");
  const kcal = (v: number | null) => (v === null ? dash : t("charts.kcal", { value: v }));

  return (
    <div className="mt-4 grid min-w-0 grid-cols-1 gap-4 min-[420px]:grid-cols-2">
      <Tile testId="tile-sessions" title={t("charts.weekly.sessions")}>
        <p className={VALUE}>{t("charts.weekly.sessionsValue", { done: data.sessions_done, planned: data.sessions_planned })}</p>
        {data.sessions_missed > 0 && <p className="text-step--1 text-slate">{t("charts.weekly.missed", { count: data.sessions_missed })}</p>}
      </Tile>
      <Tile testId="tile-completion" title={t("charts.weekly.completion")}>
        <p className={VALUE}>{completion === null ? dash : t("charts.percent", { value: completion })}</p>
        <Sparkline series={data.sparklines.training_completion.map((p) => ({ ...p, value: percent(p.value) }))} label={t("charts.weekly.completionTrend")} />
      </Tile>
      <Tile testId="tile-balance" title={t("charts.weekly.balance")} tag={estimated}>
        <p className={VALUE}>{kcal(data.avg_daily_balance_kcal)}</p>
        <p className="text-step--1 text-slate">{t("charts.weekly.targetBalance", { value: kcal(data.target_daily_balance_kcal) })}</p>
        <Sparkline series={data.sparklines.daily_balance_kcal} label={t("charts.weekly.balanceTrend")} />
      </Tile>
      <Tile testId="tile-weight" title={t("charts.weekly.weight")}>
        <p className={VALUE}>
          {start === null || end === null ? dash : t("charts.weekly.weightRange", { start, end, unit })}
        </p>
        <Sparkline
          series={data.sparklines.weight_avg_kg.map((p) => ({ ...p, value: displayWeight(p.value, units) }))}
          label={t("charts.weekly.weightTrend", { unit })}
        />
      </Tile>
    </div>
  );
}

/** Weekly stat tiles with sparklines (F15.2); energy values are labelled "estimated" (F13.3). */
export function WeeklySummaryView({ athleteId, units, today }: { athleteId: string; units: UnitSystem; today: string }) {
  const { t, i18n } = useTranslation();
  const currentMonday = mondayOf(today);
  const [weekStart, setWeekStart] = useState(currentMonday);
  const query = useWeeklySummary(athleteId, weekStart);
  const label = (d: string) => formatDay(d, i18n.language, DAY_FORMAT.dayMonth);

  return (
    <div className="min-w-0">
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" onClick={() => setWeekStart(addDays(weekStart, -7))} aria-label={t("charts.weekly.prev")} className="min-h-11 min-w-11 rounded-md border-2 border-iron font-bold hover:bg-line">
          {t("charts.adherence.prevGlyph")}
        </button>
        <span className="min-w-[9rem] text-center font-semibold" aria-live="polite">
          {t("charts.weekly.range", { from: label(weekStart), to: label(addDays(weekStart, 6)) })}
        </span>
        <button
          type="button"
          onClick={() => setWeekStart(addDays(weekStart, 7))}
          disabled={weekStart >= currentMonday}
          aria-label={t("charts.weekly.next")}
          className="min-h-11 min-w-11 rounded-md border-2 border-iron font-bold hover:bg-line disabled:opacity-40"
        >
          {t("charts.adherence.nextGlyph")}
        </button>
      </div>
      <ChartState query={query} isEmpty={() => false} emptyMessage="">
        {(data) => <SummaryBody data={data} units={units} />}
      </ChartState>
    </div>
  );
}
