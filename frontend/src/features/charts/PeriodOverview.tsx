import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { type PeriodSummary, usePeriodSummary } from "../../api/charts";
import { weightUnit, type UnitSystem } from "../../lib/units";
import { displayWeight, percent } from "./chartData";
import { ChartState } from "./ChartState";
import { DeltaLine, signed, TONE } from "./DeltaLine";

type Tone = (typeof TONE)[keyof typeof TONE];
import { ProgressRing } from "./ProgressRing";

const VALUE = "font-display text-step-3 font-bold leading-none";

function Ring({
  id,
  title,
  percentValue,
  caption,
  delta,
}: {
  id: string;
  title: string;
  percentValue: number | null;
  caption: string;
  delta: ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <div data-testid={`ring-${id}`} className="flex min-w-0 items-start gap-3">
      <ProgressRing
        percent={percentValue}
        label={title}
        centre={t("charts.percent", { value: percentValue ?? 0 })}
      />
      <div className="min-w-0">
        <h3 className="text-step--1 font-semibold uppercase tracking-wide text-slate">{title}</h3>
        <p className="text-step--1 text-slate">{percentValue === null ? t("charts.overview.noData") : caption}</p>
        {delta}
      </div>
    </div>
  );
}

function Kpi({
  id,
  title,
  tag,
  value,
  hint,
  delta,
}: {
  id: string;
  title: string;
  tag?: string;
  value: string | null;
  hint?: string;
  delta?: ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <section data-testid={`kpi-${id}`} className="min-w-0 border-t-4 border-iron bg-chalk pt-2">
      <h3 className="flex flex-wrap items-baseline gap-x-2 text-step--1 font-semibold uppercase tracking-wide text-slate">
        {title}
        {tag && <span className="rounded-sm bg-plate px-1.5 text-iron normal-case">{tag}</span>}
      </h3>
      <p className={VALUE} data-testid={`kpi-${id}-value`}>
        {value ?? t("charts.none")}
      </p>
      <p className="mt-1 text-step--1 text-slate">{value === null ? t("charts.overview.noData") : hint}</p>
      {delta}
    </section>
  );
}

function OverviewBody({ data, units }: { data: PeriodSummary; units: UnitSystem }) {
  const { t, i18n } = useTranslation();
  const unit = weightUnit(units);
  const { current: cur, deltas } = data;
  const period = t("charts.period.previousDays", { count: data.days });
  const number = (n: number) => n.toLocaleString(i18n.language, { maximumFractionDigits: 1 });
  const kcal = (n: number | null) => (n === null ? null : t("charts.kcal", { value: number(n) }));
  const weight = (kg: number | null) => {
    const shown = displayWeight(kg, units);
    return shown === null ? null : number(shown);
  };
  const estimated = t("charts.estimated");

  const countDelta = (v: number | null) => (
    <DeltaLine value={v} format={(n) => signed(n, number(n))} period={period} tone={TONE.good} />
  );
  const kcalDelta = (v: number | null) => (
    <DeltaLine value={v} format={(n) => signed(n, t("charts.kcal", { value: number(n) }))} period={period} tone={TONE.neutral} />
  );
  const pointsDelta = (v: number | null) => {
    const points = v === null ? null : Math.round(v * 100);
    return (
      <DeltaLine
        value={points}
        format={(n) => t("charts.delta.pts", { value: signed(n, number(n)) })}
        period={period}
        tone={TONE.good}
      />
    );
  };
  const weightDelta = (v: number | null, tone: Tone = TONE.neutral) => {
    const shown = v === null ? null : displayWeight(v, units);
    return (
      <DeltaLine
        value={shown}
        format={(n) => `${signed(n, number(n))} ${unit}`}
        period={period}
        tone={tone}
      />
    );
  };

  const sessionsPct = cur.sessions_planned > 0 ? Math.round((cur.sessions_done / cur.sessions_planned) * 100) : null;
  const training = percent(cur.avg_training_completion);
  const nutrition = percent(cur.avg_nutrition_completion);
  const volume = cur.sessions_done > 0 || cur.volume_kg > 0 ? weight(cur.volume_kg) : null;
  const start = weight(cur.weight_avg_start_kg);
  const end = weight(cur.weight_avg_end_kg);
  const change = displayWeight(cur.weight_change_kg, units);
  const rate = displayWeight(cur.weight_change_per_week_kg, units);

  return (
    <div className="min-w-0">
      <div className="grid min-w-0 grid-cols-1 gap-4 min-[420px]:grid-cols-3 min-[420px]:gap-3">
        <Ring
          id="sessions"
          title={t("charts.overview.sessions")}
          percentValue={sessionsPct}
          caption={t("charts.overview.sessionsCaption", { done: cur.sessions_done, planned: cur.sessions_planned })}
          delta={countDelta(deltas.sessions_done)}
        />
        <Ring
          id="training"
          title={t("charts.overview.trainingCompletion")}
          percentValue={training}
          caption={t("charts.overview.completionCaption")}
          delta={pointsDelta(deltas.avg_training_completion)}
        />
        <Ring
          id="nutrition"
          title={t("charts.overview.nutritionCompletion")}
          percentValue={nutrition}
          caption={t("charts.overview.completionCaption")}
          delta={pointsDelta(deltas.avg_nutrition_completion)}
        />
      </div>
      <div className="mt-6 grid min-w-0 grid-cols-1 gap-4 min-[420px]:grid-cols-2">
        <Kpi
          id="volume"
          title={t("charts.overview.volume")}
          value={volume === null ? null : `${volume} ${unit}`}
          delta={weightDelta(deltas.volume_kg, TONE.good)}
        />
        <Kpi
          id="active-days"
          title={t("charts.overview.activeDays")}
          value={number(cur.active_days)}
          hint={t("charts.overview.activeDaysHint")}
          delta={countDelta(deltas.active_days)}
        />
        <Kpi
          id="streak"
          title={t("charts.overview.streak")}
          value={t("charts.overview.streakValue", { count: data.longest_streak_days })}
          hint={t("charts.overview.streakHint")}
        />
        <Kpi
          id="records"
          title={t("charts.overview.records")}
          value={number(cur.personal_records)}
          delta={countDelta(deltas.personal_records)}
        />
        <Kpi
          id="balance"
          title={t("charts.overview.balance")}
          tag={estimated}
          value={kcal(cur.avg_daily_balance_kcal)}
          hint={t("charts.overview.targetBalance", { value: kcal(cur.target_daily_balance_kcal) ?? t("charts.none") })}
          delta={kcalDelta(deltas.avg_daily_balance_kcal)}
        />
        <Kpi
          id="eaten"
          title={t("charts.overview.eaten")}
          tag={estimated}
          value={kcal(cur.avg_daily_eaten_kcal)}
          hint={t("charts.overview.energyHint")}
          delta={kcalDelta(deltas.avg_daily_eaten_kcal)}
        />
        <Kpi
          id="burned"
          title={t("charts.overview.burned")}
          tag={estimated}
          value={kcal(cur.avg_daily_burned_exercise_kcal)}
          hint={t("charts.overview.energyHint")}
          delta={kcalDelta(deltas.avg_daily_burned_exercise_kcal)}
        />
        <Kpi
          id="weight"
          title={t("charts.overview.weight")}
          value={change === null ? null : `${signed(change, number(change))} ${unit}`}
          hint={
            start !== null && end !== null
              ? [
                  t("charts.overview.weightRange", { start, end, unit }),
                  rate === null ? null : t("charts.overview.weightRate", { value: signed(rate, number(rate)), unit }),
                ]
                  .filter(Boolean)
                  .join(" · ")
              : undefined
          }
          delta={weightDelta(deltas.weight_change_kg)}
        />
      </div>
    </div>
  );
}

/** Three progress rings and the KPI tiles of the selected period, each against the period before (F15.9, D109). */
export function PeriodOverview({
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
      {(data) => <OverviewBody data={data} units={units} />}
    </ChartState>
  );
}
