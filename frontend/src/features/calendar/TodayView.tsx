import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { type DayView, useDay } from "../../api/calendar";
import { usePlan } from "../../api/plan";
import type { Me } from "../../api/session";
import { EnergySummary } from "./EnergySummary";
import { QueryState } from "./QueryState";
import { StatusBadge } from "./StatusBadge";
import { badgeKind } from "./status";
import { paths } from "../../paths";
import { NoteThread, dayNotes, exerciseNotes, sessionNotes } from "../notes/NoteThread";
import { MealsSection } from "../meals/MealsSection";
import { TodayBanners } from "../notifications/TodayBanners";
import { DecidedSuggestions } from "../suggestions/DecidedSuggestions";
import { PendingSuggestions } from "../suggestions/PendingSuggestions";

type SessionExercise = NonNullable<DayView["session"]>["exercises"][number];

const KG_TO_LB = 2.2046226218;

/** Weight for display: stored in kg, shown in the user's units (spec §6.2). */
function formatWeight(kg: number, units: Me["units"]): string {
  return units === "imperial" ? `${Math.round(kg * KG_TO_LB * 2) / 2} lb` : `${Math.round(kg * 100) / 100} kg`;
}

function ExerciseRow({
  exercise,
  units,
  athleteId,
  notes,
  sessionId,
  canNote,
}: {
  exercise: SessionExercise;
  units: Me["units"];
  athleteId: string;
  notes: DayView["notes"];
  sessionId: string;
  canNote: boolean;
}) {
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
    <li className="border-b border-line py-2">
      <div className="flex items-baseline justify-between gap-3">
        <span className="font-semibold">{exercise.exercise.name}</span>
        <span className="text-right text-step--1 text-slate">
          {t("calendar.today.sets", { count: exercise.sets.length })}
          {target && ` · ${target}`}
        </span>
      </div>
      <NoteThread
        athleteId={athleteId}
        notes={exerciseNotes(notes, exercise.exercise.id)}
        target={canNote ? { scope: "exercise", exercise_id: exercise.exercise.id, session_id: sessionId } : undefined}
        label={exercise.exercise.name}
      />
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

/** Who edited a plan day by hand, shown only for a coach ("edited by <coach name>", F8.3). */
export function coachEditor(editedBy: { display_name: string; role: string } | null | undefined): string | null {
  return editedBy?.role === "coach" ? editedBy.display_name : null;
}

function EditedBy({ name }: { name: string | null }) {
  const { t } = useTranslation();
  if (!name) return null;
  return <p className="mt-1 text-step--1 font-semibold text-slate">{t("plan.editedBy", { name })}</p>;
}

/** Read-only meal list for the coach context: the planned meals and whether they were eaten. */
function ReadOnlyMeals({ day }: { day: DayView }) {
  const { t } = useTranslation();
  if (day.meals.length === 0) return <p className="mt-2 text-slate">{t("calendar.noMeals")}</p>;
  return (
    <ul className="mt-2">
      {day.meals.map(({ planned_meal: planned, log }) => (
        <li key={planned.id} className="flex flex-wrap items-baseline justify-between gap-x-3 border-b border-line py-2">
          <span className="min-w-0 break-words">
            <span className="text-step--1 font-semibold uppercase text-slate">{t(`calendar.today.slot.${planned.slot}`)}</span>{" "}
            {planned.meal.name}
          </span>
          <span className="text-step--1 text-slate">
            {log ? t(`meals.status.${log.status as "eaten" | "adjusted" | "skipped"}`) : t("calendar.today.notLogged")}
          </span>
        </li>
      ))}
    </ul>
  );
}

/**
 * Today (spec F9): the athlete's session, meals, estimated energy balance and pending items.
 * `readOnly` is the coach context (F16.4): no workout link, no meal logging, no own banners; the
 * pending suggestions stay actionable (F11).
 */
export function TodayView({
  me,
  readOnly = false,
  sessionLink,
  date = "today",
}: {
  me: Pick<Me, "id" | "units">;
  readOnly?: boolean;
  sessionLink?: (sessionId: string) => string;
  /** `today` (the user's day) or an ISO date, e.g. the day a coach note refers to. */
  date?: string;
}) {
  const { t } = useTranslation();
  const day = useDay(me.id, date);
  const plan = usePlan(me.id);

  if (!day.data) {
    return <QueryState isPending={day.isPending} isError={day.isError} onRetry={() => void day.refetch()} />;
  }

  const { session, energy } = day.data;
  const kind = badgeKind(day.data.training_status, day.data.training_completion);
  return (
    <>
      {!readOnly && <TodayBanners />}

      <Section id="today-training" title={t("calendar.today.training")}>
        <p className="mt-2 flex items-center gap-3 text-step-1">
          <StatusBadge kind={kind} />
          <span className="font-semibold">{session?.training_day_name ?? t("calendar.restDay")}</span>
        </p>
        <EditedBy name={coachEditor(plan.data?.training_days.find((d) => d.weekday === day.data.weekday)?.edited_by)} />
        {session && readOnly && sessionLink && (
          <Link to={sessionLink(session.id)} className="mt-3 inline-flex min-h-11 items-center font-semibold text-spruce underline underline-offset-4">
            {t("coach.client.sessionDetail")}
          </Link>
        )}
        {session && !readOnly && (
          <Link
            to={paths.workout(session.id)}
            className="mt-3 inline-flex min-h-12 w-full items-center justify-center rounded-md bg-spruce px-5 font-semibold text-chalk hover:bg-spruce-dark sm:w-auto"
          >
            {t(session.status === "planned" ? "calendar.today.startWorkout" : session.status === "done" ? "calendar.today.viewWorkout" : "calendar.today.continueWorkout")}
          </Link>
        )}
        {session && (
          <NoteThread
            athleteId={me.id}
            notes={sessionNotes(day.data.notes)}
            target={readOnly ? { scope: "session", session_id: session.id } : undefined}
            label={t("notes.sessionLabel")}
          />
        )}
        {session && (
          <ul className="mt-2">
            {session.exercises.map((exercise) => (
              <ExerciseRow
                key={exercise.planned_exercise_id ?? exercise.order}
                exercise={exercise}
                units={me.units}
                athleteId={me.id}
                notes={day.data.notes}
                sessionId={session.id}
                canNote={readOnly}
              />
            ))}
          </ul>
        )}
      </Section>

      <Section id="today-meals" title={t("calendar.today.meals")}>
        <EditedBy name={coachEditor(plan.data?.meal_days.find((d) => d.weekday === day.data.weekday)?.edited_by)} />
        {readOnly ? <ReadOnlyMeals day={day.data} /> : <MealsSection athleteId={me.id} day={day.data} />}
      </Section>

      <Section id="today-energy" title={t("calendar.today.energy")}>
        <EnergySummary energy={energy} compact={false} />
      </Section>

      <PendingSuggestions athleteId={me.id} units={me.units} className="mt-8 border-t-4 border-plate pt-3" />
      <DecidedSuggestions athleteId={me.id} units={me.units} className="mt-8 border-t-4 border-plate pt-3" />

      {(readOnly || dayNotes(day.data.notes).length > 0) && (
        <Section id="today-notes" title={t("notes.dayTitle")}>
          <NoteThread
            athleteId={me.id}
            notes={dayNotes(day.data.notes)}
            target={readOnly ? { scope: "day", date: day.data.date } : undefined}
            label={t("notes.dayLabel")}
          />
        </Section>
      )}
    </>
  );
}
