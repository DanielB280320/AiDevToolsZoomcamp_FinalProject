import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { isApiError } from "../../api/errors";
import type { Me } from "../../api/session";
import {
  type ExerciseSummary,
  type FinishSessionResult,
  type SessionExercise,
  type SetLogInput,
  useFinishSession,
  useLogSet,
  useSession,
} from "../../api/workout";
import { paths } from "../../paths";
import { QueryState } from "../calendar/QueryState";
import { useDay } from "../../api/calendar";
import { dayNotes, exerciseNotes, NoteThread, sessionNotes } from "../notes/NoteThread";
import { type Clock, systemClock } from "./clock";
import { ExerciseAdder } from "./ExerciseAdder";
import { ExerciseCard, type SetSaver } from "./ExerciseCard";
import { FinishSummary, percent } from "./FinishSummary";
import { RestTimer } from "./RestTimer";
import { useRestTimer } from "./useRestTimer";

/** Rest used for an exercise added on the spot (spec F10 default). */
const DEFAULT_REST_SECONDS = 90;

const ERROR_CODES = ["edit_window_closed", "invalid_set"] as const;

function errorKey(error: unknown): (typeof ERROR_CODES)[number] | "generic" {
  if (isApiError(error)) {
    const code = ERROR_CODES.find((c) => c === error.problem.code);
    if (code) return code;
  }
  return "generic";
}

function addedExercise(exercise: ExerciseSummary): SessionExercise {
  return {
    planned_exercise_id: null,
    exercise,
    order: 0,
    is_extra: true,
    rule: null,
    sets: [],
    reps_min: null,
    reps_max: null,
    rest_seconds: DEFAULT_REST_SECONDS,
    calibration_hint: null,
    completion: null,
    pending_suggestion_id: null,
  };
}

/** Live workout (spec F10, §6.1): one tap logs a set as planned, then the rest timer runs. */
export function WorkoutScreen({ me, sessionId, clock = systemClock }: { me: Me; sessionId: string; clock?: Clock }) {
  const { t } = useTranslation();
  const session = useSession(sessionId);
  const day = useDay(me.id, session.data?.date); // the coach notes of the workout's day
  const logSet = useLogSet(sessionId);
  const finish = useFinishSession(sessionId);
  const timer = useRestTimer(clock);
  const [result, setResult] = useState<FinishSessionResult | null>(null);
  const [added, setAdded] = useState<ExerciseSummary[]>([]);

  if (!session.data) {
    return <QueryState isPending={session.isPending} isError={session.isError} onRetry={() => void session.refetch()} />;
  }
  const data = session.data;
  const locked = Date.parse(data.editable_until) < clock.now();

  const save: SetSaver = async (exerciseId, plannedExerciseId, setNo, input) => {
    const body: SetLogInput = { exercise_id: exerciseId, planned_exercise_id: plannedExerciseId, set_no: setNo, as_planned: false, skipped: false, ...input };
    try {
      await logSet.mutateAsync(body);
      return true;
    } catch {
      return false; // shown below from `logSet.error`
    }
  };

  const present = new Set(data.exercises.filter((e) => e.is_extra).map((e) => e.exercise.id));
  const exercises = [
    ...data.exercises,
    ...added.filter((e) => !present.has(e.id) && !data.exercises.some((x) => x.exercise.id === e.id)).map(addedExercise),
  ];

  const onFinish = () => {
    if (finish.isPending) return;
    finish.mutate(undefined, {
      onSuccess: (finished) => {
        timer.stop(); // the workout is over: no rest to wait for
        setResult(finished);
      },
    });
  };

  return (
    <div>
      <h1 className="font-display text-step-4 font-bold leading-tight">{data.training_day_name}</h1>
      <p className="mt-1 text-slate">
        {data.status === "done" ? t("workout.statusDone") : t("workout.progress", { value: percent(data.completion) })}
      </p>

      {day.data && (
        <>
          <NoteThread athleteId={me.id} notes={dayNotes(day.data.notes)} label={t("notes.dayLabel")} />
          <NoteThread athleteId={me.id} notes={sessionNotes(day.data.notes)} label={t("notes.sessionLabel")} />
        </>
      )}

      {locked && (
        <p role="status" className="mt-3 border-l-4 border-plate pl-3">
          {t("workout.locked")}
        </p>
      )}

      {result ? (
        <FinishSummary result={result} athleteId={me.id} units={me.units} onReview={() => setResult(null)} />
      ) : (
        <>
          {data.exercises.some((e) => e.pending_suggestion_id !== null) && (
            <p role="status" className="mt-3 border-l-4 border-plate pl-3">
              {t("workout.suggestionPending")}
            </p>
          )}
          {logSet.isError && (
            <p role="alert" className="mt-3 border-l-4 border-alert pl-3 text-alert">
              {t(`workout.errors.${errorKey(logSet.error)}`)}
            </p>
          )}
          {exercises.map((exercise) => (
            <ExerciseCard
              key={exercise.planned_exercise_id ?? exercise.exercise.id}
              exercise={exercise}
              notes={day.data ? exerciseNotes(day.data.notes, exercise.exercise.id) : []}
              athleteId={me.id}
              units={me.units}
              locked={locked}
              pending={logSet.isPending}
              save={save}
              onDiscard={(gone) => setAdded(added.filter((e) => e.id !== gone.exercise.id))}
              onLogged={(done) => timer.start(done.rest_seconds, done.exercise.name)}
            />
          ))}
          {!locked && <ExerciseAdder onPick={(exercise) => setAdded([...added, exercise])} />}

          {!locked && (
            <div className="mt-8 border-t-4 border-spruce pt-4">
              {finish.isError && (
                <p role="alert" className="mb-3 border-l-4 border-alert pl-3 text-alert">
                  {t(`workout.errors.${errorKey(finish.error)}`)}
                </p>
              )}
              <button
                type="button"
                onClick={onFinish}
                aria-disabled={finish.isPending || undefined}
                className="min-h-14 w-full rounded-md bg-iron px-5 font-display text-step-1 font-bold text-chalk hover:bg-spruce-dark aria-disabled:opacity-75 sm:w-auto"
              >
                {finish.isPending
                  ? t("workout.finishing")
                  : data.status === "done"
                    ? t("workout.finishAgain")
                    : t("workout.finish")}
              </button>
            </div>
          )}
          <p className="mt-4">
            <Link to={paths.today} className="font-semibold text-spruce underline underline-offset-4">
              {t("workout.backToToday")}
            </Link>
          </p>
        </>
      )}
      <RestTimer timer={timer} />
    </div>
  );
}
