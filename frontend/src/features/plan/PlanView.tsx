import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { Plan, PlannedExercise } from "../../api/plan";
import { formatWeight, type UnitSystem } from "../../lib/units";
import { DayRow } from "./DayRow";

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
  const [open, setOpen] = useState<ReadonlySet<string>>(() => new Set());
  const toggle = (id: string) =>
    setOpen(
      (was) =>
        new Set(was.has(id) ? [...was].filter((x) => x !== id) : [...was, id]),
    );
  return (
    <div>
      <h3 className="font-display text-step-2 font-bold">{t("plan.view.training")}</h3>
      {plan.training_days.length === 0 && <p className="text-slate">{t("plan.training.empty")}</p>}
      <ul className="mt-2 flex flex-col gap-4">
        {plan.training_days.map((day) => (
          <DayRow
            key={day.id}
            id={`view-day-${day.id}`}
            open={open.has(day.id)}
            onToggle={() => toggle(day.id)}
            title={t("plan.training.dayTitle", {
              weekday: t(`plan.weekday.${day.weekday}`),
              name: day.name,
            })}
            summary={
              day.exercises.length === 0
                ? t("plan.days.noExercises")
                : t("plan.days.exercises", { count: day.exercises.length })
            }
            note={
              day.edited_by?.role === "coach" ? (
                <p className="text-step--1 font-semibold text-slate">
                  {t("plan.editedBy", { name: day.edited_by.display_name })}
                </p>
              ) : null
            }
          >
            <ul>
              {day.exercises.map((exercise) => (
                <li key={exercise.id} className="break-words">
                  {exercise.exercise.name}: <Target exercise={exercise} units={units} />
                </li>
              ))}
            </ul>
          </DayRow>
        ))}
      </ul>
      <h3 className="mt-6 font-display text-step-2 font-bold">{t("plan.view.meals")}</h3>
      {plan.meal_days.length === 0 && <p className="text-slate">{t("plan.meals.empty")}</p>}
      <ul className="mt-2 flex flex-col gap-4">
        {plan.meal_days.map((day) => (
          <DayRow
            key={day.id}
            id={`view-meal-${day.id}`}
            open={open.has(day.id)}
            onToggle={() => toggle(day.id)}
            title={t(`plan.weekdayLong.${day.weekday}`)}
            summary={
              day.meals.length === 0
                ? t("plan.days.noMeals")
                : t("plan.days.meals", { count: day.meals.length })
            }
            note={
              day.edited_by?.role === "coach" ? (
                <p className="text-step--1 font-semibold text-slate">
                  {t("plan.editedBy", { name: day.edited_by.display_name })}
                </p>
              ) : null
            }
          >
            <ul>
              {day.meals.map((meal) => (
                <li key={meal.id} className="break-words">
                  {t("plan.view.meal", { slot: t(`plan.slot.${meal.slot}`), name: meal.meal.name, kcal: meal.totals.kcal })}
                </li>
              ))}
            </ul>
          </DayRow>
        ))}
      </ul>
    </div>
  );
}
