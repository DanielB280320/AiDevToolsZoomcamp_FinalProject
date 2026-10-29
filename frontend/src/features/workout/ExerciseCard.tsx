import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { SessionExercise, SessionSet, SetLogInput, ExerciseSummary } from "../../api/workout";
import type { UnitSystem } from "../../lib/units";
import { SetEditor } from "./SetEditor";
import { describeValues } from "./values";

export interface SetSaver {
  /** Logs one set; resolves `true` when the server accepted it. */
  (exerciseId: string, plannedExerciseId: string | null, setNo: number, input: Partial<SetLogInput>): Promise<boolean>;
}

interface Props {
  exercise: SessionExercise;
  units: UnitSystem;
  locked: boolean;
  pending: boolean;
  save: SetSaver;
  /** Called after a set was logged (not skipped), to start the rest timer. */
  onLogged: (exercise: SessionExercise) => void;
  /** Called when an added extra exercise with no logged sets is cancelled, so it can be dropped. */
  onDiscard?: (exercise: SessionExercise) => void;
}

function SetRow({
  exercise,
  set,
  units,
  locked,
  pending,
  save,
  onLogged,
}: Props & { set: SessionSet }) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const { log } = set;
  const target = describeValues(
    t,
    { reps: set.target_reps, weight_kg: set.target_weight_kg, seconds: set.target_seconds },
    units,
  );
  const hasTarget = set.target_reps != null || set.target_seconds != null || set.target_weight_kg != null;
  const name = t("workout.setName", { number: set.set_no });

  const submit = async (input: Partial<SetLogInput>) => {
    const ok = await save(exercise.exercise.id, exercise.planned_exercise_id, set.set_no, input);
    if (!ok) return;
    setEditing(false);
    if (!input.skipped) onLogged(exercise);
  };

  return (
    <li className="border-b border-line py-3">
      <div className="flex items-baseline justify-between gap-3">
        <span className="font-semibold">
          {name}
          {set.is_extra && <span className="ml-2 text-step--1 font-normal text-slate">{t("workout.extra")}</span>}
        </span>
        <span className="text-right text-step--1 text-slate">
          {target ? t("workout.target", { value: target }) : t("workout.noTarget")}
        </span>
      </div>
      {log && (
        <p className="mt-1 font-semibold text-spruce">
          <span aria-hidden="true">{log.skipped ? t("workout.glyph.skipped") : t("workout.glyph.logged")}</span>
          {log.skipped
            ? t("workout.skipped")
            : t("workout.logged", { value: describeValues(t, log, units) })}
        </p>
      )}
      {!locked && !editing && (
        <div className="mt-2 flex flex-wrap gap-2">
          {!log && hasTarget && (
            <button
              type="button"
              aria-disabled={pending || undefined}
              onClick={() => {
                if (!pending) void submit({ as_planned: true });
              }}
              className="min-h-12 rounded-md bg-spruce px-5 font-semibold text-chalk hover:bg-spruce-dark aria-disabled:opacity-75"
            >
              {t("workout.asPlanned")}
              <span className="sr-only"> {t("workout.forSet", { exercise: exercise.exercise.name, number: set.set_no })}</span>
            </button>
          )}
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="min-h-12 rounded-md border-2 border-iron px-4 font-semibold hover:bg-line"
          >
            {t("workout.edit")}
            <span className="sr-only"> {t("workout.forSet", { exercise: exercise.exercise.name, number: set.set_no })}</span>
          </button>
          {!log && (
            <button
              type="button"
              aria-disabled={pending || undefined}
              onClick={() => {
                if (!pending) void submit({ skipped: true });
              }}
              className="min-h-12 rounded-md px-4 font-semibold text-spruce underline underline-offset-4"
            >
              {t("workout.skip")}
              <span className="sr-only"> {t("workout.forSet", { exercise: exercise.exercise.name, number: set.set_no })}</span>
            </button>
          )}
        </div>
      )}
      {editing && (
        <SetEditor
          exercise={exercise.exercise}
          initial={{
            reps: log?.reps ?? set.target_reps,
            weight_kg: log?.weight_kg ?? set.target_weight_kg,
            seconds: log?.seconds ?? set.target_seconds,
            distance_m: log?.distance_m ?? null,
          }}
          units={units}
          pending={pending}
          onSave={(values) => void submit(values)}
          onCancel={() => setEditing(false)}
        />
      )}
    </li>
  );
}

/** One exercise of the session: its sets, plus "Add set" for extras beyond the plan. */
export function ExerciseCard(props: Props) {
  const { t } = useTranslation();
  const { exercise, locked, save, onLogged } = props;
  const [adding, setAdding] = useState(false);
  const nextSetNo = exercise.sets.reduce((max, s) => Math.max(max, s.set_no), 0) + 1;

  // An extra exercise has no sets until the first is logged: open the editor straight away.
  const showEditor = adding || (exercise.is_extra && exercise.sets.length === 0 && !locked);

  return (
    <section aria-labelledby={`ex-${exercise.exercise.id}`} className="mt-6 border-t-4 border-iron pt-3">
      <h2 id={`ex-${exercise.exercise.id}`} className="font-display text-step-2 font-bold">
        {exercise.exercise.name}
      </h2>
      <p className="text-step--1 text-slate">{t("workout.restPlanned", { count: exercise.rest_seconds })}</p>
      <ol>
        {exercise.sets.map((set) => (
          <SetRow key={set.set_no} {...props} set={set} />
        ))}
      </ol>
      {showEditor && (
        <SetEditor
          exercise={exercise.exercise}
          initial={{}}
          units={props.units}
          pending={props.pending}
          onSave={(values) => {
            void save(exercise.exercise.id, exercise.planned_exercise_id, nextSetNo, values).then((ok) => {
              if (!ok) return;
              setAdding(false);
              onLogged(exercise);
            });
          }}
          onCancel={() => {
            setAdding(false);
            if (exercise.is_extra && exercise.sets.length === 0) props.onDiscard?.(exercise);
          }}
        />
      )}
      {!locked && !showEditor && (
        <button
          type="button"
          onClick={() => setAdding(true)}
          className="mt-3 min-h-12 rounded-md border-2 border-iron px-4 font-semibold hover:bg-line"
        >
          {t("workout.addSet")}
          <span className="sr-only"> {exercise.exercise.name}</span>
        </button>
      )}
    </section>
  );
}

export type { ExerciseSummary };
