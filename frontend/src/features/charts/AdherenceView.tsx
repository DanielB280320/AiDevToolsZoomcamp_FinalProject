import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Bar, BarChart, CartesianGrid, Legend, XAxis, YAxis } from "recharts";

import { type AdherenceChart, type AdherenceDay, useAdherenceChart } from "../../api/charts";
import { addMonths, DAY_FORMAT, formatDay, monthGridRange, monthOf } from "../../lib/calendarDates";
import { ChartBox } from "./ChartBox";
import { CHART_COLORS, percent } from "./chartData";
import { ChartState } from "./ChartState";

type Metric = "training" | "nutrition";
const METRICS: Metric[] = ["training", "nutrition"];

const ratioOf = (day: AdherenceDay, metric: Metric) =>
  metric === "training" ? day.training_completion : day.nutrition_completion;

/**
 * One heat-map cell. `null` (rest, planned, future, no plan) is a neutral dashed cell with no
 * number: it is "not applicable", never 0 %. A missed session is a real 0 % in the low-end colour.
 */
function Cell({ day, metric, locale }: { day: AdherenceDay; metric: Metric; locale: string }) {
  const { t } = useTranslation();
  const pct = percent(ratioOf(day, metric));
  const date = formatDay(day.date, locale, DAY_FORMAT.dayMonth);
  const label =
    pct === null
      ? t("charts.adherence.cellNeutral", { date, status: t(`charts.adherence.trainingStatus.${day.training_status}`) })
      : t("charts.adherence.cellValue", { date, value: pct });
  const style = pct === null ? undefined : { backgroundColor: `rgba(30, 107, 87, ${0.12 + 0.88 * (pct / 100)})` };
  return (
    <li
      data-testid="heat-cell"
      data-value={pct === null ? "none" : pct}
      aria-label={label}
      title={label}
      style={style}
      className={`flex aspect-square min-w-0 items-center justify-center rounded-sm text-step--1 font-semibold ${
        pct === null ? "border border-dashed border-line bg-chalk text-slate" : pct >= 60 ? "text-chalk" : "border border-alert/40 text-iron"
      }`}
    >
      <span aria-hidden="true">{day.date.slice(8)}</span>
    </li>
  );
}

function AdherenceBody({ data, metric }: { data: AdherenceChart; metric: Metric }) {
  const { t, i18n } = useTranslation();
  // The grid starts on a Monday; pad so the first API day sits in the right column.
  const lead = Array.from({ length: data.days[0] ? (new Date(`${data.days[0].date}T00:00:00Z`).getUTCDay() + 6) % 7 : 0 });
  const weeks = data.weeks.map((w) => ({
    week: w.week_start,
    value: percent(metric === "training" ? w.training_completion : w.nutrition_completion),
  }));

  return (
    <div className="min-w-0">
      <ol className="mt-3 grid max-w-[28rem] grid-cols-7 gap-1" aria-label={t("charts.adherence.heatLabel")}>
        {lead.map((_, i) => (
          <li key={`pad-${i}`} aria-hidden="true" />
        ))}
        {data.days.map((d) => (
          <Cell key={d.date} day={d} metric={metric} locale={i18n.language} />
        ))}
      </ol>
      <p className="mt-2 text-step--1 text-slate">{t("charts.adherence.legend")}</p>
      <h3 className="mt-6 font-display text-step-1 font-bold">{t("charts.adherence.weekly")}</h3>
      <ChartBox label={t("charts.adherence.weeklyLabel")} height={180}>
        <BarChart data={weeks} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
          <CartesianGrid stroke={CHART_COLORS.line} vertical={false} />
          <XAxis dataKey="week" tickFormatter={(d: string) => formatDay(d, i18n.language, DAY_FORMAT.dayMonth)} minTickGap={16} />
          <YAxis domain={[0, 100]} unit="%" width={48} />
          <Legend />
          <Bar dataKey="value" name={t(`charts.adherence.${metric}`)} fill={CHART_COLORS.actual} isAnimationActive={false} />
        </BarChart>
      </ChartBox>
    </div>
  );
}

/** Adherence (F15.2): a month heat map of daily completion plus the weekly bars for the same weeks. */
export function AdherenceView({ athleteId, today }: { athleteId: string; today: string }) {
  const { t, i18n } = useTranslation();
  const [month, setMonth] = useState(monthOf(today));
  const [metric, setMetric] = useState<Metric>("training");
  const { from, to } = monthGridRange(month);
  const query = useAdherenceChart(athleteId, from, to);
  const monthLabel = formatDay(`${month}-01`, i18n.language, DAY_FORMAT.monthYear);

  return (
    <div className="min-w-0">
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" onClick={() => setMonth(addMonths(month, -1))} aria-label={t("charts.adherence.prev")} className="min-h-11 min-w-11 rounded-md border-2 border-iron font-bold hover:bg-line">
          {t("charts.adherence.prevGlyph")}
        </button>
        <span className="min-w-[9rem] text-center font-semibold" aria-live="polite">
          {monthLabel}
        </span>
        <button type="button" onClick={() => setMonth(addMonths(month, 1))} aria-label={t("charts.adherence.next")} className="min-h-11 min-w-11 rounded-md border-2 border-iron font-bold hover:bg-line">
          {t("charts.adherence.nextGlyph")}
        </button>
      </div>
      <fieldset className="mt-3 min-w-0">
        <legend className="sr-only">{t("charts.adherence.metric")}</legend>
        <div className="flex gap-2">
          {METRICS.map((m) => (
            <label key={m} className={`flex min-h-11 cursor-pointer items-center rounded-md border-2 border-iron px-3 font-semibold ${metric === m ? "bg-iron text-chalk" : "hover:bg-line"}`}>
              <input type="radio" name="adherence-metric" value={m} checked={metric === m} onChange={() => setMetric(m)} className="sr-only" />
              {t(`charts.adherence.${m}`)}
            </label>
          ))}
        </div>
      </fieldset>
      <div className="mt-3">
        <ChartState query={query} isEmpty={(d) => d.days.length === 0} emptyMessage={t("charts.adherence.empty")}>
          {(data) => <AdherenceBody data={data} metric={metric} />}
        </ChartState>
      </div>
    </div>
  );
}
