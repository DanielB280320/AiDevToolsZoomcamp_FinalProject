import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { type DayView, useDay } from "../../api/calendar";
import type { Me } from "../../api/session";
import { QueryState } from "./QueryState";
import { StatusBadge } from "./StatusBadge";
import { badgeKind } from "./status";
import { paths } from "../../paths";
import { MealsSection } from "../meals/MealsSection";
import { PendingSuggestions } from "../suggestions/PendingSuggestions";

type SessionExercise = NonNullable<DayView["session"]>["exercises"][number];

const KG_TO_LB = 2.2046226218;

/** Weight for display: stored in kg, shown in the user's units (spec §6.2). */
function formatWeight(kg: number, units: Me["units"]): string {
  return units === "imperial" ? `${Math.round(kg * KG_TO_LB * 2) / 2} lb` : `${Math.round(kg * 100) / 100} kg`;
}

function ExerciseRow({ exercise, units }: { exercise: SessionExercise; units: Me["units"] }) {
  const { t } = useTranslation();
  const first = exercise.sets[0];
  const target = [
    first?.target_reps != null ? t("calendar.today.reps", { count: first.target_reps }) : null,
    first?.target_seconds != null ? t("calendar.today.seconds", { count: first.target_seconds }) : null,
    first?.target_weight_kg != null ? formatWeight(first.target_weight_kg, units) : null,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <li className="flex items-baseline justify-between gap-3 border-b border-line py-2">
      <span className="font-semibold">{exercise.exercise.name}</span>
      <span className="text-right text-step--1 text-slate">
        {t("calendar.today.sets", { count: exercise.sets.length })}
        {target && ` · ${target}`}
      </span>
    </li>
  );
}

function Section({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  return (
    <section aria-labelledby={id} className="mt-8 border-t-4 border-iron pt-3">
      <h2 id={id} className="font-display text-step-2 font-bold">
        {title}
      </h2>
      {children}
    </section>
  );
}

/** Today (spec F9): the athlete's session, meals, estimated energy balance and pending items. */
export function TodayView({ me }: { me: Me }) {
  const { t } = useTranslation();
  const day = useDay(me.id, "today");

  if (!day.data) {
    return <QueryState isPending={day.isPending} isError={day.isError} onRetry={() => void day.refetch()} />;
  }

  const { session, energy } = day.data;
  const kind = badgeKind(day.data.training_status, day.data.training_completion);
  return (
    <>
      <Section id="today-training" title={t("calendar.today.training")}>
        <p className="mt-2 flex items-center gap-3 text-step-1">
          <StatusBadge kind={kind} />
          <span className="font-semibold">{session?.training_day_name ?? t("calendar.restDay")}</span>
        </p>
        {session && (
          <Link
            to={paths.workout(session.id)}
            className="mt-3 inline-flex min-h-12 w-full items-center justify-center rounded-md bg-spruce px-5 font-semibold text-chalk hover:bg-spruce-dark sm:w-auto"
          >
            {t(session.status === "planned" ? "calendar.today.startWorkout" : session.status === "done" ? "calendar.today.viewWorkout" : "calendar.today.continueWorkout")}
          </Link>
        )}
        {session && (
          <ul className="mt-2">
            {session.exercises.map((exercise) => (
              <ExerciseRow key={exercise.planned_exercise_id ?? exercise.order} exercise={exercise} units={me.units} />
            ))}
          </ul>
        )}
      </Section>

      <Section id="today-meals" title={t("calendar.today.meals")}>
        <MealsSection athleteId={me.id} day={day.data} />
      </Section>

      <Section id="today-energy" title={t("calendar.today.energy")}>
        <dl className="mt-2 grid grid-cols-3 gap-3 text-center">
          <div>
            <dt className="text-step--1 text-slate">{t("calendar.today.eaten")}</dt>
            <dd className="font-display text-step-2 font-bold">{energy.eaten.kcal}</dd>
          </div>
          <div>
            <dt className="text-step--1 text-slate">{t("calendar.today.burned")}</dt>
            <dd className="font-display text-step-2 font-bold">{energy.burned.total_kcal}</dd>
          </div>
          <div>
            <dt className="text-step--1 text-slate">{t("calendar.today.balance")}</dt>
            <dd className="font-display text-step-2 font-bold">{energy.balance_kcal}</dd>
          </div>
        </dl>
        <p className="mt-2 text-step--1 text-slate">{t("calendar.today.estimated")}</p>
      </Section>

      <PendingSuggestions athleteId={me.id} units={me.units} className="mt-8 border-t-4 border-plate pt-3" />

      {day.data.notes.length > 0 && (
        <p className="mt-8 border-t-4 border-plate pt-3">
          {t("calendar.today.attention", { notes: day.data.notes.length })}
        </p>
      )}
    </>
  );
}
