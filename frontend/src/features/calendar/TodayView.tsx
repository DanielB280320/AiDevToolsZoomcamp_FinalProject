import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { type DayView, useDay } from "../../api/calendar";
import { usePlan } from "../../api/plan";
import type { Me } from "../../api/session";
import { DayChecklist, MEALS_SECTION_ID, SUGGESTIONS_SECTION_ID, TRAINING_SECTION_ID } from "./DayChecklist";
import { EnergySummary } from "./EnergySummary";
import { QueryState } from "./QueryState";
import { StatusBadge } from "./StatusBadge";
import { badgeKind } from "./status";
import { CheckCircleIcon, ChevronDownIcon, DumbbellIcon, FlameIcon, LightbulbIcon, NoteIcon, UtensilsIcon } from "../../components/icons";
import { PrBadge } from "../../components/PrBadge";
import { paths } from "../../paths";
import { SessionExerciseChart } from "../charts/SessionChartView";
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

/** A completion ratio (0-1, F10.2) as a whole percent, kept inside 0-100 for the charts. */
export function toPercent(completion: number): number {
  return Math.min(100, Math.max(0, Math.round(completion * 100)));
}

const RING_RADIUS = 30;
const RING_LENGTH = 2 * Math.PI * RING_RADIUS;

/** Session completion as a ring with the percent in the middle (F10.11). */
export function CompletionRing({ percent }: { percent: number }) {
  const { t } = useTranslation();
  return (
    <div className="mt-3 flex items-center gap-3" data-testid="session-completion">
      <div
        role="progressbar"
        aria-label={t("calendar.today.sessionCompletionLabel")}
        aria-valuemin={0}
        aria-valuenow={percent}
        aria-valuemax={100}
        className="relative h-20 w-20 shrink-0"
      >
        <svg viewBox="0 0 72 72" className="h-full w-full -rotate-90" aria-hidden="true">
          <circle cx="36" cy="36" r={RING_RADIUS} fill="none" strokeWidth="8" className="stroke-line" />
          <circle
            cx="36"
            cy="36"
            r={RING_RADIUS}
            fill="none"
            strokeWidth="8"
            strokeLinecap={percent > 0 && percent < 100 ? "round" : "butt"}
            strokeDasharray={RING_LENGTH}
            strokeDashoffset={RING_LENGTH * (1 - percent / 100)}
            className="stroke-spruce"
          />
        </svg>
        <span className="absolute inset-0 flex items-center justify-center font-display text-step-1 font-bold">
          {t("calendar.today.percent", { value: percent })}
        </span>
      </div>
      <span className="font-semibold">{t("calendar.today.sessionCompletionLabel")}</span>
    </div>
  );
}

function ExerciseRow({
  exercise,
  units,
  athleteId,
  notes,
  sessionId,
  canNote,
  finished,
}: {
  exercise: SessionExercise;
  units: Me["units"];
  athleteId: string;
  notes: DayView["notes"];
  sessionId: string;
  canNote: boolean;
  /** The session is finished: show how much of the exercise was completed (F10.2 per exercise, D97). */
  finished: boolean;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const chartId = useId();
  const first = exercise.sets[0];
  const target = [
    first?.target_reps != null ? t("calendar.today.reps", { count: first.target_reps }) : null,
    first?.target_seconds != null ? t("calendar.today.seconds", { count: first.target_seconds }) : null,
    first?.target_weight_kg != null ? formatWeight(first.target_weight_kg, units) : null,
  ]
    .filter(Boolean)
    .join(" · ");
  const percent = finished && exercise.completion != null ? toPercent(exercise.completion) : null;
  return (
    <li className="border-b border-line py-2">
      <div className="flex items-center justify-between gap-3">
        <span className="font-semibold">
          <button
            type="button"
            aria-expanded={open}
            aria-controls={chartId}
            onClick={() => setOpen((was) => !was)}
            className="inline-flex min-h-11 items-center gap-1 text-left font-semibold hover:text-spruce"
          >
            <ChevronDownIcon className={`size-5 text-spruce transition-transform ${open ? "rotate-180" : ""}`} />
            {exercise.exercise.name}
          </button>{" "}
          {exercise.is_pr && <PrBadge />}
        </span>
        <span className="shrink-0 text-right text-step--1 text-slate">
          {t("calendar.today.sets", { count: exercise.sets.length })}
          {target && ` · ${target}`}
          {percent != null && (
            <span className="mt-1 block" data-testid="exercise-completion">
              <span className="block font-semibold text-iron">{t("calendar.today.exerciseCompletion", { value: percent })}</span>
              <span
                role="progressbar"
                aria-label={t("calendar.today.exerciseCompletionLabel", { name: exercise.exercise.name })}
                aria-valuemin={0}
                aria-valuenow={percent}
                aria-valuemax={100}
                className="mt-1 ml-auto block h-2 w-28 overflow-hidden rounded-full bg-line"
              >
                <span className="block h-full bg-spruce" style={{ width: `${percent}%` }} />
              </span>
            </span>
          )}
        </span>
      </div>
      {open && (
        <div
          id={chartId}
          role="region"
          aria-label={t("calendar.today.exerciseChartRegion", { name: exercise.exercise.name })}
          className="mt-1 min-w-0"
          data-testid="exercise-session-chart"
        >
          <SessionExerciseChart athleteId={athleteId} sessionId={sessionId} exerciseId={exercise.exercise.id} units={units} />
        </div>
      )}
      <NoteThread
        athleteId={athleteId}
        notes={exerciseNotes(notes, exercise.exercise.id)}
        target={canNote ? { scope: "exercise", exercise_id: exercise.exercise.id, session_id: sessionId } : undefined}
        label={exercise.exercise.name}
      />
    </li>
  );
}

const SECTION_ICON = "size-7 text-spruce";

function Section({
  id,
  title,
  icon,
  description,
  children,
}: {
  id: string;
  title: string;
  icon: React.ReactNode;
  /** What the section is and whether the reader is expected to act (D99). */
  description: string;
  children: React.ReactNode;
}) {
  return (
    <section aria-labelledby={id} className="mt-8 border-t-4 border-iron pt-3">
      <h2 id={id} className="flex items-center gap-2 font-display text-step-2 font-bold">
        {icon}
        {title}
      </h2>
      <p className="mt-1 text-step--1 text-slate" data-testid="section-description">
        {description}
      </p>
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
 * Today (spec F9): the day checklist (what is still open, D100), the estimated energy balance, the meals, the session, then the pending and
 * the recently decided suggestions (D98).
 * `readOnly` is the coach context (F16.4): no workout link, no meal logging, no own banners; the
 * pending suggestions stay actionable (F11).
 */
export function TodayView({
  me,
  readOnly = false,
  sessionLink,
  date = "today",
}: {
  /** `timezone` is the athlete's zone, used for the dates of the recent decisions. */
  me: Pick<Me, "id" | "units"> & { timezone?: string };
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
  const who = readOnly ? "coach" : "athlete";
  const trainingState = !session ? "rest" : session.status === "done" ? "done" : session.status === "planned" ? "planned" : "inProgress";
  return (
    <>
      <DayChecklist day={day.data} athleteId={me.id} who={who} units={me.units} progressLink={readOnly ? undefined : paths.progress} />
      {!readOnly && <TodayBanners />}

      <Section id="today-energy" description={t("calendar.today.about.energy")} title={t("calendar.today.energy")} icon={<FlameIcon className={SECTION_ICON} />}>
        <EnergySummary energy={energy} compact={false} />
      </Section>

      <Section id={MEALS_SECTION_ID} description={t(`calendar.today.about.meals.${who}`)} title={t("calendar.today.meals")} icon={<UtensilsIcon className={SECTION_ICON} />}>
        <EditedBy name={coachEditor(plan.data?.meal_days.find((d) => d.weekday === day.data.weekday)?.edited_by)} />
        {readOnly ? <ReadOnlyMeals day={day.data} /> : <MealsSection athleteId={me.id} day={day.data} />}
      </Section>

      <Section id={TRAINING_SECTION_ID} description={t(`calendar.today.about.training.${who}.${trainingState}`)} title={t("calendar.today.training")} icon={<DumbbellIcon className={SECTION_ICON} />}>
        <p className="mt-2 flex items-center gap-3 text-step-1">
          <StatusBadge kind={kind} />
          <span className="font-semibold">{session?.training_day_name ?? t("calendar.restDay")}</span>
        </p>
        {session?.status === "done" && session.completion != null && <CompletionRing percent={toPercent(session.completion)} />}
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
                finished={session.status === "done"}
              />
            ))}
          </ul>
        )}
      </Section>

      <PendingSuggestions
        id={SUGGESTIONS_SECTION_ID}
        athleteId={me.id}
        units={me.units}
        className="mt-8 border-t-4 border-plate pt-3"
        icon={<LightbulbIcon className={SECTION_ICON} />}
        description={t("calendar.today.about.suggestions")}
      />
      <DecidedSuggestions
        athleteId={me.id}
        units={me.units}
        timezone={me.timezone}
        className="mt-8 border-t-4 border-plate pt-3"
        icon={<CheckCircleIcon className={SECTION_ICON} />}
        description={t("calendar.today.about.decisions")}
      />

      {(readOnly || dayNotes(day.data.notes).length > 0) && (
        <Section id="today-notes" description={t(`calendar.today.about.notes.${who}`)} title={t("notes.dayTitle")} icon={<NoteIcon className={SECTION_ICON} />}>
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
