import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, XAxis, YAxis } from "recharts";

import { DEFAULT_CHART_WEEKS, type ChartWeeks, type ExerciseChart, useExerciseChart } from "../../api/charts";
import { useExerciseSearch } from "../../api/onboarding";
import { DAY_FORMAT, formatDay } from "../../lib/calendarDates";
import { weightUnit, type UnitSystem } from "../../lib/units";
import { ChartBox } from "./ChartBox";
import { AUTO_DOMAIN, CHART_COLORS, displayWeight, hasValues } from "./chartData";
import { ChartState } from "./ChartState";
import { RangeSelector } from "./RangeSelector";

interface PrDotProps {
  cx?: number;
  cy?: number;
  payload?: { is_pr: boolean };
}

/** A star on points that are personal records; ordinary points keep a plain dot. */
function PrDot({ cx, cy, payload }: PrDotProps) {
  if (cx === undefined || cy === undefined || !payload) return null;
  if (!payload.is_pr) return <circle cx={cx} cy={cy} r={3} fill={CHART_COLORS.actual} />;
  return (
    <polygon
      data-testid="pr-marker"
      points={`${cx},${cy - 8} ${cx + 2.4},${cy - 2.5} ${cx + 8},${cy - 2.5} ${cx + 3.6},${cy + 1.5} ${cx + 5},${cy + 7.5} ${cx},${cy + 4} ${cx - 5},${cy + 7.5} ${cx - 3.6},${cy + 1.5} ${cx - 8},${cy - 2.5} ${cx - 2.4},${cy - 2.5}`}
      fill={CHART_COLORS.accent}
      stroke={CHART_COLORS.ink}
      strokeWidth={1}
    />
  );
}

function ExerciseBody({ data, units }: { data: ExerciseChart; units: UnitSystem }) {
  const { t, i18n } = useTranslation();
  const unit = weightUnit(units);
  const rows = data.points.map((p) => ({
    date: p.date,
    target: displayWeight(p.target_weight_kg, units),
    top: displayWeight(p.top_set_weight_kg, units),
    volume: displayWeight(p.volume_kg, units),
    is_pr: p.is_pr,
  }));
  const hasWeights = hasValues(rows, "top") || hasValues(rows, "target");
  const prs = rows.filter((r) => r.is_pr);
  const dayLabel = (iso: string) => formatDay(iso, i18n.language, DAY_FORMAT.dayMonth);

  return (
    <div className="mt-4 min-w-0">
      {hasWeights ? (
        <ChartBox label={t("charts.exercise.weightLabel", { name: data.exercise.name, unit })}>
          <LineChart data={rows} margin={{ top: 12, right: 12, bottom: 0, left: -12 }}>
            <CartesianGrid stroke={CHART_COLORS.line} vertical={false} />
            <XAxis dataKey="date" tickFormatter={dayLabel} minTickGap={24} />
            <YAxis domain={AUTO_DOMAIN} unit={` ${unit}`} width={56} />
            <Legend />
            <Line dataKey="target" name={t("charts.exercise.target")} stroke={CHART_COLORS.target} strokeDasharray="5 4" dot={false} connectNulls isAnimationActive={false} />
            <Line dataKey="top" name={t("charts.exercise.topSet")} stroke={CHART_COLORS.actual} strokeWidth={2} dot={<PrDot />} connectNulls isAnimationActive={false} />
          </LineChart>
        </ChartBox>
      ) : (
        <p className="text-slate">{t("charts.exercise.noWeights")}</p>
      )}
      {prs.length > 0 && (
        <p className="mt-2 text-step--1 text-slate" data-testid="pr-list">
          {t("charts.exercise.prs", { dates: prs.map((p) => `${dayLabel(p.date)} (${p.top} ${unit})`).join(", ") })}
        </p>
      )}
      <h3 className="mt-6 font-display text-step-1 font-bold">{t("charts.exercise.volume", { unit })}</h3>
      <ChartBox label={t("charts.exercise.volumeLabel", { name: data.exercise.name, unit })} height={180}>
        <BarChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
          <CartesianGrid stroke={CHART_COLORS.line} vertical={false} />
          <XAxis dataKey="date" tickFormatter={dayLabel} minTickGap={24} />
          <YAxis width={56} />
          <Bar dataKey="volume" name={t("charts.exercise.volumeName")} fill={CHART_COLORS.actual} isAnimationActive={false} />
        </BarChart>
      </ChartBox>
    </div>
  );
}

/** Exercise over time (F15.2): pick an exercise from the catalog, then a range of 4/12/26/52 weeks. */
export function ExerciseChartView({ athleteId, units }: { athleteId: string; units: UnitSystem }) {
  const { t } = useTranslation();
  const [text, setText] = useState("");
  const [chosen, setChosen] = useState<{ id: string; name: string } | null>(null);
  const [weeks, setWeeks] = useState<ChartWeeks>(DEFAULT_CHART_WEEKS);
  const search = useExerciseSearch(text);
  const query = useExerciseChart(athleteId, chosen?.id ?? null, weeks);

  return (
    <div className="min-w-0">
      <label htmlFor="exercise-search" className="block font-semibold">
        {t("charts.exercise.search")}
      </label>
      <input
        id="exercise-search"
        type="search"
        value={text}
        onChange={(e) => setText(e.target.value)}
        className="mt-1 min-h-12 w-full max-w-[24rem] rounded-md border-2 border-iron bg-chalk px-3"
      />
      {search.data && search.data.length > 0 && text.trim() !== chosen?.name && (
        <ul className="mt-2 flex flex-wrap gap-2">
          {search.data.map((e) => (
            <li key={e.id}>
              <button
                type="button"
                onClick={() => {
                  setChosen({ id: e.id, name: e.name });
                  setText(e.name);
                }}
                className="min-h-11 rounded-md border-2 border-iron px-3 font-semibold hover:bg-line"
              >
                {e.name}
              </button>
            </li>
          ))}
        </ul>
      )}
      {chosen === null ? (
        <p className="mt-3 text-slate">{t("charts.exercise.pick")}</p>
      ) : (
        <>
          <h3 className="mt-4 font-display text-step-1 font-bold">{chosen.name}</h3>
          <RangeSelector value={weeks} onChange={setWeeks} />
          <div className="mt-3">
            <ChartState query={query} isEmpty={(d) => d.points.length === 0} emptyMessage={t("charts.exercise.empty")}>
              {(data) => <ExerciseBody data={data} units={units} />}
            </ChartState>
          </div>
        </>
      )}
    </div>
  );
}
