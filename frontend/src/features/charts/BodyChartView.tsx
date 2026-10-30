import { useState } from "react";
import { useTranslation } from "react-i18next";
import { CartesianGrid, Legend, Line, LineChart, XAxis, YAxis } from "recharts";

import { DEFAULT_CHART_WEEKS, type BodyChart, type ChartWeeks, useBodyChart } from "../../api/charts";
import { DAY_FORMAT, formatDay } from "../../lib/calendarDates";
import { weightUnit, type UnitSystem } from "../../lib/units";
import { ChartBox } from "./ChartBox";
import { AUTO_DOMAIN, CHART_COLORS, displayWeight, hasValues } from "./chartData";
import { ChartState } from "./ChartState";
import { RangeSelector } from "./RangeSelector";

function BodyBody({ data, units }: { data: BodyChart; units: UnitSystem }) {
  const { t, i18n } = useTranslation();
  const unit = weightUnit(units);
  const rows = data.points.map((p) => ({
    date: p.date,
    weight: displayWeight(p.weight_kg, units),
    avg: displayWeight(p.weight_avg_7d_kg, units),
    fat: p.body_fat_pct,
  }));
  const dayLabel = (iso: string) => formatDay(iso, i18n.language, DAY_FORMAT.dayMonth);
  const hasFat = hasValues(rows, "fat");

  return (
    <div className="min-w-0">
      <ChartBox label={t("charts.body.weightLabel", { unit })}>
        <LineChart data={rows} margin={{ top: 12, right: 12, bottom: 0, left: -12 }}>
          <CartesianGrid stroke={CHART_COLORS.line} vertical={false} />
          <XAxis dataKey="date" tickFormatter={dayLabel} minTickGap={24} />
          <YAxis domain={AUTO_DOMAIN} unit={` ${unit}`} width={56} />
          <Legend />
          <Line dataKey="weight" name={t("charts.body.weight")} stroke={CHART_COLORS.target} strokeWidth={0} dot={{ r: 3 }} connectNulls={false} isAnimationActive={false} />
          <Line dataKey="avg" name={t("charts.body.avg")} stroke={CHART_COLORS.actual} strokeWidth={2} dot={false} connectNulls isAnimationActive={false} />
        </LineChart>
      </ChartBox>
      {hasFat && (
        <>
          <h3 className="mt-6 flex flex-wrap items-baseline gap-x-2 font-display text-step-1 font-bold">
            {t("charts.body.fat")}
            <span className="rounded-sm bg-plate px-1.5 text-step--1 font-semibold">{t("charts.estimated")}</span>
          </h3>
          <ChartBox label={t("charts.body.fatLabel")} height={180}>
            <LineChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
              <CartesianGrid stroke={CHART_COLORS.line} vertical={false} />
              <XAxis dataKey="date" tickFormatter={dayLabel} minTickGap={24} />
              <YAxis domain={AUTO_DOMAIN} unit="%" width={48} />
              <Line dataKey="fat" name={t("charts.body.fat")} stroke={CHART_COLORS.alert} strokeWidth={2} dot={{ r: 3 }} connectNulls isAnimationActive={false} />
            </LineChart>
          </ChartBox>
        </>
      )}
    </div>
  );
}

/** Body trend (F15.2): weigh-ins with the 7-day average, and body fat when present. */
export function BodyChartView({ athleteId, units }: { athleteId: string; units: UnitSystem }) {
  const { t } = useTranslation();
  const [weeks, setWeeks] = useState<ChartWeeks>(DEFAULT_CHART_WEEKS);
  const query = useBodyChart(athleteId, weeks);
  return (
    <div className="min-w-0">
      <RangeSelector value={weeks} onChange={setWeeks} />
      <div className="mt-3">
        <ChartState query={query} isEmpty={(d) => d.points.length === 0} emptyMessage={t("charts.body.empty")}>
          {(data) => <BodyBody data={data} units={units} />}
        </ChartState>
      </div>
    </div>
  );
}
