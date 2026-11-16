import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { Bar, BarChart, CartesianGrid, Legend, XAxis, YAxis } from "recharts";

import { type AdherenceChart, type AdherenceDay, useAdherenceChart } from "../../api/charts";
import { DAY_FORMAT, formatDay, monthOf } from "../../lib/calendarDates";
import { ChartBox } from "./ChartBox";
import { ChartTooltip, TOOLTIP_UNIT } from "./ChartTooltip";
import { CHART_COLORS, percent } from "./chartData";
import { ChartState } from "./ChartState";
import { useChartAnimation } from "../../lib/motion";

/** Above this many days the heat map shows one calendar month at a time (D113), so a year stays a short grid. */
const PAGED_ABOVE_DAYS = 31;

type Metric = "training" | "nutrition";
const METRICS: Metric[] = ["training", "nutrition"];

const ratioOf = (day: AdherenceDay, metric: Metric) =>
  metric === "training" ? day.training_completion : day.nutrition_completion;

const STEP =
  "min-h-11 min-w-11 rounded-control border border-edge hover:border-slate font-semibold hover:bg-line disabled:cursor-not-allowed disabled:opacity-40";

/** Where the detail box sits over its cell: it opens inwards on the outer columns so it never leaves the card. */
const tipAlign = (column: number) => (column <= 1 ? "left-0" : column >= 5 ? "right-0" : "left-1/2 -translate-x-1/2");

/** The detail box of a day (D113): the date, then training and nutrition, whichever metric colours the grid. */
function DayDetail({ id, day, column, locale }: { id: string; day: AdherenceDay; column: number; locale: string }) {
  const { t } = useTranslation();
  const status = t(`charts.adherence.trainingStatus.${day.training_status}`);
  const training = percent(day.training_completion);
  const nutrition = percent(day.nutrition_completion);
  return (
    <div
      id={id}
      role="tooltip"
      data-testid="heat-detail"
      className={`pointer-events-none absolute bottom-full z-10 mb-1 w-max max-w-[13rem] rounded-control border border-line bg-card px-2.5 py-1.5 text-left text-step--1 text-iron shadow-[0_4px_12px_rgb(28_37_48/0.12)] ${tipAlign(column)}`}
    >
      <p className="font-semibold">{formatDay(day.date, locale, DAY_FORMAT.weekdayDayMonthLong)}</p>
      <p>
        {t("charts.adherence.tipTraining", {
          value: training === null ? status : t("charts.adherence.tipPercentStatus", { value: training, status }),
        })}
      </p>
      <p>
        {t("charts.adherence.tipNutrition", {
          value: nutrition === null ? t("charts.adherence.tipNone") : t("charts.adherence.tipPercent", { value: nutrition }),
        })}
      </p>
    </div>
  );
}

/**
 * One heat-map cell. `null` (rest, planned, future, no plan) is a neutral dashed cell with no
 * number: it is "not applicable", never 0 %. A missed session is a real 0 % in the low-end colour.
 * Pointing at, focusing or tapping the cell opens the day's detail box.
 */
function Cell({
  day,
  metric,
  locale,
  column,
  open,
  onOpen,
  onClose,
}: {
  day: AdherenceDay;
  metric: Metric;
  locale: string;
  column: number;
  open: boolean;
  onOpen: () => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const tipId = useId();
  const pct = percent(ratioOf(day, metric));
  const date = formatDay(day.date, locale, DAY_FORMAT.dayMonth);
  const label =
    pct === null
      ? t("charts.adherence.cellNeutral", { date, status: t(`charts.adherence.trainingStatus.${day.training_status}`) })
      : t("charts.adherence.cellValue", { date, value: pct });
  const style = pct === null ? undefined : { backgroundColor: `rgba(30, 107, 87, ${0.12 + 0.88 * (pct / 100)})` };
  return (
    <li className="relative min-w-0" onMouseEnter={onOpen} onMouseLeave={onClose}>
      <button
        type="button"
        data-testid="heat-cell"
        data-value={pct === null ? "none" : pct}
        aria-label={label}
        aria-describedby={open ? tipId : undefined}
        onFocus={onOpen}
        onBlur={onClose}
        onClick={onOpen}
        onKeyDown={(e) => {
          if (e.key === "Escape") onClose();
        }}
        style={style}
        className={`flex aspect-square w-full min-w-0 items-center justify-center rounded-sm text-step--1 font-semibold ${
          pct === null ? "border border-dashed border-line bg-page text-slate" : pct >= 60 ? "text-chalk" : "border border-alert/40 text-iron"
        }`}
      >
        <span aria-hidden="true">{day.date.slice(8)}</span>
      </button>
      {open && <DayDetail id={tipId} day={day} column={column} locale={locale} />}
    </li>
  );
}

function AdherenceBody({ data, metric }: { data: AdherenceChart; metric: Metric }) {
  const { t, i18n } = useTranslation();
  const anim = useChartAnimation();
  const [picked, setPicked] = useState<string | null>(null);
  const [openDate, setOpenDate] = useState<string | null>(null);

  // A long period is paged by calendar month and opens on its latest month (D113).
  const paged = data.days.length > PAGED_ABOVE_DAYS;
  const months = [...new Set(data.days.map((d) => monthOf(d.date)))];
  const at = picked !== null && months.includes(picked) ? months.indexOf(picked) : months.length - 1;
  const month = months[at];
  const days = paged ? data.days.filter((d) => monthOf(d.date) === month) : data.days;
  const go = (delta: number) => {
    setPicked(months[at + delta] ?? null);
    setOpenDate(null);
  };

  // The grid starts on a Monday; pad so the first shown day sits in the right column.
  const lead = days[0] ? (new Date(`${days[0].date}T00:00:00Z`).getUTCDay() + 6) % 7 : 0;
  const weeks = data.weeks.map((w) => ({
    week: w.week_start,
    value: percent(metric === "training" ? w.training_completion : w.nutrition_completion),
  }));

  return (
    <div className="min-w-0">
      <div className="mx-auto mt-3 max-w-[28rem]">
        {paged && month && (
          <div className="mb-2 flex items-center gap-2">
            <button type="button" onClick={() => go(-1)} disabled={at === 0} aria-label={t("charts.adherence.prevMonth")} className={STEP}>
              {t("charts.period.prevGlyph")}
            </button>
            <span className="min-w-0 flex-1 text-center font-semibold" aria-live="polite" data-testid="heat-month">
              {formatDay(`${month}-01`, i18n.language, DAY_FORMAT.monthYear)}
            </span>
            <button
              type="button"
              onClick={() => go(1)}
              disabled={at === months.length - 1}
              aria-label={t("charts.adherence.nextMonth")}
              className={STEP}
            >
              {t("charts.period.nextGlyph")}
            </button>
          </div>
        )}
        <ol className="grid grid-cols-7 gap-1" aria-label={t("charts.adherence.heatLabel")}>
          {Array.from({ length: lead }, (_, i) => (
            <li key={`pad-${i}`} aria-hidden="true" />
          ))}
          {days.map((d, i) => (
            <Cell
              key={d.date}
              day={d}
              metric={metric}
              locale={i18n.language}
              column={(lead + i) % 7}
              open={openDate === d.date}
              onOpen={() => setOpenDate(d.date)}
              onClose={() => setOpenDate((cur) => (cur === d.date ? null : cur))}
            />
          ))}
        </ol>
      </div>
      <p className="mx-auto mt-2 max-w-[28rem] text-step--1 text-slate">{t("charts.adherence.legend")}</p>
      <h3 className="mt-6 font-display text-step-1 font-semibold">{t("charts.adherence.weekly")}</h3>
      <ChartBox label={t("charts.adherence.weeklyLabel")} height={180}>
        <BarChart data={weeks} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={CHART_COLORS.line} vertical={false} />
          <XAxis dataKey="week" tickFormatter={(d: string) => formatDay(d, i18n.language, DAY_FORMAT.dayMonth)} minTickGap={16} />
          <YAxis domain={[0, 100]} unit="%" width="auto" />
          <ChartTooltip label={(d: string) => formatDay(d, i18n.language, DAY_FORMAT.dayMonth)} unit={TOOLTIP_UNIT.percent} bars />
          <Legend />
          <Bar dataKey="value" name={t(`charts.adherence.${metric}`)} fill={CHART_COLORS.actual} {...anim} />
        </BarChart>
      </ChartBox>
    </div>
  );
}

/** Adherence (F15.2, D109): a heat map of daily completion for the selected period plus the weekly bars. */
export function AdherenceView({ athleteId, from, to }: { athleteId: string; from: string; to: string }) {
  const { t } = useTranslation();
  const [metric, setMetric] = useState<Metric>("training");
  const query = useAdherenceChart(athleteId, from, to);

  return (
    <div className="min-w-0">
      <fieldset className="min-w-0">
        <legend className="sr-only">{t("charts.adherence.metric")}</legend>
        <div className="flex gap-2">
          {METRICS.map((m) => (
            <label key={m} className={`flex min-h-11 cursor-pointer items-center rounded-control border border-edge hover:border-slate px-3 font-semibold ${metric === m ? "bg-iron text-chalk" : "hover:bg-line"}`}>
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
