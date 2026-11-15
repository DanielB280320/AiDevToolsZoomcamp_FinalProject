import { useTranslation } from "react-i18next";
import { Bar, CartesianGrid, ComposedChart, Legend, Line, LineChart, XAxis, YAxis } from "recharts";

import { type PeriodSummary, usePeriodSummary } from "../../api/charts";
import { DAY_FORMAT, formatDay } from "../../lib/calendarDates";
import { weightUnit, type UnitSystem } from "../../lib/units";
import { ChartBox } from "./ChartBox";
import { AUTO_DOMAIN, CHART_COLORS, displayWeight, hasValues, percent } from "./chartData";
import { ChartState, EmptyState } from "./ChartState";

/**
 * The same numbers as a chart, as a table for screen readers (F15.9). The table sits in a
 * `sr-only` box: a table ignores the 1 px width of `sr-only` itself and would widen the page.
 */
function DataTable({ caption, head, rows }: { caption: string; head: string[]; rows: (string | number | null)[][] }) {
  const { t } = useTranslation();
  return (
    <div className="sr-only">
      <table>
        <caption>{caption}</caption>
        <thead>
          <tr>
            {head.map((h) => (
              <th key={h} scope="col">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={String(row[0])}>
              {row.map((cell, i) => (
                <td key={i}>{cell === null ? t("charts.none") : cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Heading({ children, estimated }: { children: string; estimated?: string }) {
  return (
    <h3 className="mt-6 flex flex-wrap items-baseline gap-x-2 font-display text-step-1 font-bold first:mt-0">
      {children}
      {estimated && <span className="rounded-sm bg-plate px-1.5 text-step--1 font-semibold">{estimated}</span>}
    </h3>
  );
}

function TimelinesBody({ data, units }: { data: PeriodSummary; units: UnitSystem }) {
  const { t, i18n } = useTranslation();
  const unit = weightUnit(units);
  const bucket = t(data.bucket === "day" ? "charts.timelines.bucketDay" : "charts.timelines.bucketWeek");
  const target = data.current.target_daily_balance_kcal;
  const rows = data.series.map((p) => ({
    start: p.start,
    volume: displayWeight(p.volume_kg, units),
    sessions: p.sessions_done,
    training: percent(p.training_completion),
    nutrition: percent(p.nutrition_completion),
    balance: p.balance_kcal,
    target: p.balance_kcal === null ? null : target,
  }));
  const tick = (iso: string) => formatDay(iso, i18n.language, DAY_FORMAT.dayMonth);
  const rowLabel = (iso: string) =>
    data.bucket === "day" ? tick(iso) : t("charts.timelines.weekOf", { date: tick(iso) });
  const margin = { top: 8, right: 8, bottom: 0, left: -12 };
  const hasVolume = rows.some((r) => r.sessions > 0 || (r.volume ?? 0) > 0);
  const hasCompletion = hasValues(rows, "training") || hasValues(rows, "nutrition");
  const hasBalance = hasValues(rows, "balance");
  const volumeTitle = t("charts.timelines.volume");
  const completionTitle = t("charts.timelines.completion");
  const balanceTitle = t("charts.timelines.balance");
  const caption = (title: string) => t("charts.timelines.tableCaption", { title });
  const startHead = t("charts.timelines.period");

  return (
    <div className="min-w-0">
      <Heading>{volumeTitle}</Heading>
      {hasVolume ? (
        <>
          <ChartBox label={t("charts.timelines.volumeLabel", { unit, bucket })} height={200}>
            <ComposedChart data={rows} margin={margin}>
              <CartesianGrid stroke={CHART_COLORS.line} vertical={false} />
              <XAxis dataKey="start" tickFormatter={tick} minTickGap={24} />
              <YAxis yAxisId="volume" width={48} />
              <YAxis yAxisId="sessions" orientation="right" allowDecimals={false} width={32} />
              <Legend />
              <Bar yAxisId="volume" dataKey="volume" name={t("charts.timelines.volumeName", { unit })} fill={CHART_COLORS.actual} isAnimationActive={false} />
              <Line yAxisId="sessions" dataKey="sessions" name={t("charts.timelines.sessionsName")} stroke={CHART_COLORS.ink} strokeWidth={2} dot={{ r: 3 }} isAnimationActive={false} />
            </ComposedChart>
          </ChartBox>
          <DataTable
            caption={caption(volumeTitle)}
            head={[startHead, t("charts.timelines.volumeName", { unit }), t("charts.timelines.sessionsName")]}
            rows={rows.map((r) => [rowLabel(r.start), r.volume, r.sessions])}
          />
        </>
      ) : (
        <EmptyState>{t("charts.timelines.volumeEmpty")}</EmptyState>
      )}

      <Heading>{completionTitle}</Heading>
      {hasCompletion ? (
        <>
          <ChartBox label={t("charts.timelines.completionLabel", { bucket })} height={200}>
            <LineChart data={rows} margin={margin}>
              <CartesianGrid stroke={CHART_COLORS.line} vertical={false} />
              <XAxis dataKey="start" tickFormatter={tick} minTickGap={24} />
              <YAxis domain={[0, 100]} unit="%" width={48} />
              <Legend />
              <Line dataKey="training" name={t("charts.timelines.trainingName")} stroke={CHART_COLORS.actual} strokeWidth={2} dot={{ r: 2 }} connectNulls isAnimationActive={false} />
              <Line dataKey="nutrition" name={t("charts.timelines.nutritionName")} stroke={CHART_COLORS.accent} strokeWidth={2} strokeDasharray="5 4" dot={{ r: 2 }} connectNulls isAnimationActive={false} />
            </LineChart>
          </ChartBox>
          <DataTable
            caption={caption(completionTitle)}
            head={[startHead, t("charts.timelines.trainingName"), t("charts.timelines.nutritionName")]}
            rows={rows.map((r) => [rowLabel(r.start), r.training === null ? null : `${r.training}%`, r.nutrition === null ? null : `${r.nutrition}%`])}
          />
        </>
      ) : (
        <EmptyState>{t("charts.timelines.completionEmpty")}</EmptyState>
      )}

      <Heading estimated={t("charts.estimated")}>{balanceTitle}</Heading>
      {hasBalance ? (
        <>
          <ChartBox label={t("charts.timelines.balanceLabel", { bucket })} height={200}>
            <LineChart data={rows} margin={margin}>
              <CartesianGrid stroke={CHART_COLORS.line} vertical={false} />
              <XAxis dataKey="start" tickFormatter={tick} minTickGap={24} />
              <YAxis domain={AUTO_DOMAIN} width={56} />
              <Legend />
              <Line dataKey="balance" name={t("charts.timelines.balanceName")} stroke={CHART_COLORS.actual} strokeWidth={2} dot={{ r: 2 }} connectNulls isAnimationActive={false} />
              <Line dataKey="target" name={t("charts.timelines.targetName")} stroke={CHART_COLORS.target} strokeDasharray="5 4" dot={false} connectNulls isAnimationActive={false} />
            </LineChart>
          </ChartBox>
          <DataTable
            caption={caption(balanceTitle)}
            head={[startHead, t("charts.timelines.balanceName"), t("charts.timelines.targetName")]}
            rows={rows.map((r) => [
              rowLabel(r.start),
              r.balance === null ? null : t("charts.kcal", { value: r.balance }),
              r.target === null ? null : t("charts.kcal", { value: r.target }),
            ])}
          />
        </>
      ) : (
        <EmptyState>{t("charts.timelines.balanceEmpty")}</EmptyState>
      )}
    </div>
  );
}

/** Volume with sessions, completion and energy balance over the selected period (F15.9, D109). */
export function PeriodTimelines({
  athleteId,
  units,
  from,
  to,
}: {
  athleteId: string;
  units: UnitSystem;
  from: string;
  to: string;
}) {
  const query = usePeriodSummary(athleteId, from, to);
  return (
    <ChartState query={query} isEmpty={() => false} emptyMessage="">
      {(data) => <TimelinesBody data={data} units={units} />}
    </ChartState>
  );
}
