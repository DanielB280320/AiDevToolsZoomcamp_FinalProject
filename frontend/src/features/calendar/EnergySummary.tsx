import { useTranslation } from "react-i18next";

import type { DayView } from "../../api/calendar";

type Energy = DayView["energy"];

const MACROS = [
  { key: "protein", field: "protein_g" },
  { key: "carbs", field: "carbs_g" },
  { key: "fat", field: "fat_g" },
] as const;

function MacroBar({ label, eaten, target }: { label: string; eaten: number; target: number }) {
  const { t } = useTranslation();
  const ratio = target > 0 ? Math.min(eaten / target, 1) : 0;
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2 text-step--1">
        <span className="font-semibold">{label}</span>
        <span className="text-slate">{t("calendar.energy.macroValue", { eaten: Math.round(eaten), target: Math.round(target) })}</span>
      </div>
      <div
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuenow={Math.round(eaten)}
        aria-valuemax={Math.round(target)}
        className="mt-1 h-2 overflow-hidden rounded-full bg-line"
      >
        <div className="h-full bg-spruce" style={{ width: `${Math.round(ratio * 100)}%` }} />
      </div>
    </div>
  );
}

/**
 * Estimated energy balance of one day (spec F13.3): eaten, burned, balance, the goal's target balance
 * and macro progress bars. Used by Today (`compact={false}`) and the Week day cards (`compact`).
 */
export function EnergySummary({ energy, compact }: { energy: Energy; compact: boolean }) {
  const { t } = useTranslation();
  const figures: [string, number][] = [
    [compact ? t("calendar.energy.eaten") : t("calendar.today.eaten"), energy.eaten.kcal],
    [compact ? t("calendar.energy.burned") : t("calendar.today.burned"), energy.burned.total_kcal],
    [compact ? t("calendar.energy.balance") : t("calendar.today.balance"), energy.balance_kcal],
    [compact ? t("calendar.energy.targetBalance") : t("calendar.today.targetBalance"), energy.target_balance_kcal],
  ];
  return (
    <div>
      <dl className="mt-2 grid grid-cols-2 gap-3 text-center min-[420px]:grid-cols-4">
        {figures.map(([label, value]) => (
          <div key={label}>
            <dt className="text-step--1 text-slate">{label}</dt>
            <dd className={`font-display font-bold ${compact ? "text-step-1" : "text-step-2"}`}>{value}</dd>
          </div>
        ))}
      </dl>
      {energy.target.kcal > 0 && (
        <div role="group" aria-label={t("calendar.energy.macros")} className="mt-3 grid gap-2">
          {MACROS.map(({ key, field }) => (
            <MacroBar key={key} label={t(`calendar.energy.${key}`)} eaten={energy.eaten[field]} target={energy.target[field]} />
          ))}
        </div>
      )}
      <p className="mt-2 text-step--1 text-slate">{compact ? t("calendar.energy.estimatedTag") : t("calendar.today.estimated")}</p>
    </div>
  );
}
