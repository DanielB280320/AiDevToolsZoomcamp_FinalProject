import { useTranslation } from "react-i18next";

import { useMealSwaps, type MealSwap } from "../../api/plan";
import { BUTTON } from "./fields";

/**
 * Alternatives with about the same kcal as a saved meal (F7, F8, D86). Read-only until the athlete picks one;
 * the parent turns the pick into a new meal (no id, so a new meal_key and no logs, D73) and saves it.
 */
export function MealSwaps({
  athleteId,
  mealKey,
  mealName,
  pending,
  onPick,
  onClose,
}: {
  athleteId: string;
  mealKey: string;
  mealName: string;
  pending: boolean;
  onPick: (swap: MealSwap) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const swaps = useMealSwaps(athleteId, mealKey, true);
  return (
    <div role="group" aria-label={t("plan.meals.swap.title", { name: mealName })} className="mt-3 border-l-4 border-iron pl-3">
      <h5 className="font-display text-step-1 font-bold">{t("plan.meals.swap.heading")}</h5>
      {swaps.isPending && <p role="status">{t("plan.meals.swap.loading")}</p>}
      {swaps.isError && (
        <p role="alert" className="font-semibold text-alert">
          {t("plan.meals.swap.failed")}
        </p>
      )}
      {swaps.data && swaps.data.alternatives.length === 0 && <p>{t("plan.meals.swap.none")}</p>}
      {swaps.data && swaps.data.alternatives.length > 0 && (
        <ul className="mt-2 flex flex-col gap-2">
          {swaps.data.alternatives.map((alt) => (
            <li key={alt.meal_id} className="flex items-center justify-between gap-3">
              <span className="min-w-0 break-words">
                <span className="font-semibold">{alt.name}</span>
                <span className="block text-step--1 text-slate">
                  {t("plan.meals.swap.detail", { kcal: Math.round(alt.totals.kcal), portion: alt.portion_factor })}
                </span>
              </span>
              <button type="button" className={BUTTON} disabled={pending} onClick={() => onPick(alt)} aria-label={t("plan.meals.swap.use", { name: alt.name })}>
                {t("plan.meals.swap.useButton")}
              </button>
            </li>
          ))}
        </ul>
      )}
      <button type="button" className={`${BUTTON} mt-2`} onClick={onClose}>
        {t("plan.meals.swap.close")}
      </button>
    </div>
  );
}
