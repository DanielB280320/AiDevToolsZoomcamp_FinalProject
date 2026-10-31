import { useTranslation } from "react-i18next";

import type { Plan, PlannedExercise } from "../../api/plan";
import { formatWeight, type UnitSystem } from "../../lib/units";

function Target({ exercise, units }: { exercise: PlannedExercise; units: UnitSystem }) {
  const { t } = useTranslation();
  if (exercise.target_seconds !== null) {
    return <>{t("plan.view.timed", { sets: exercise.sets, seconds: exercise.target_seconds })}</>;
  }
  const reps =
    exercise.reps_max !== null && exercise.reps_max !== exercise.reps_min
      ? `${exercise.reps_min}-${exercise.reps_max}`
      : String(exercise.reps_min ?? "");
  const weight = exercise.target_weight_kg === null ? t("plan.view.calibrate") : formatWeight(exercise.target_weight_kg, units);
  return <>{t("plan.view.sets", { sets: exercise.sets, reps, weight })}</>;
}

/** Read-only plan (an older version, F8.2): the same days and meals as the editor, without inputs. */
export function PlanView({ plan, units }: { plan: Plan; units: UnitSystem }) {
  const { t } = useTranslation();
  return (
    <div>
      <h3 className="font-display text-step-2 font-bold">{t("plan.view.training")}</h3>
      {plan.training_days.length === 0 && <p className="text-slate">{t("plan.training.empty")}</p>}
      <ul className="mt-2 flex flex-col gap-4">
        {plan.training_days.map((day) => (
          <li key={day.id} className="border-l-4 border-plate pl-3">
            <h4 className="font-display text-step-1 font-bold">
              {t("plan.training.dayTitle", { weekday: t(`plan.weekday.${day.weekday}`), name: day.name })}
            </h4>
            {day.edited_by && <p className="text-step--1 font-semibold text-slate">{t("plan.editedBy", { name: day.edited_by.display_name })}</p>}
            <ul>
              {day.exercises.map((exercise) => (
                <li key={exercise.id} className="break-words">
                  {exercise.exercise.name}: <Target exercise={exercise} units={units} />
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
      <h3 className="mt-6 font-display text-step-2 font-bold">{t("plan.view.meals")}</h3>
      {plan.meal_days.length === 0 && <p className="text-slate">{t("plan.meals.empty")}</p>}
      <ul className="mt-2 flex flex-col gap-4">
        {plan.meal_days.map((day) => (
          <li key={day.id} className="border-l-4 border-plate pl-3">
            <h4 className="font-display text-step-1 font-bold">{t(`plan.weekdayLong.${day.weekday}`)}</h4>
            {day.edited_by && <p className="text-step--1 font-semibold text-slate">{t("plan.editedBy", { name: day.edited_by.display_name })}</p>}
            <ul>
              {day.meals.map((meal) => (
                <li key={meal.id} className="break-words">
                  {t("plan.view.meal", { slot: t(`plan.slot.${meal.slot}`), name: meal.meal.name, kcal: meal.totals.kcal })}
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
    </div>
  );
}
