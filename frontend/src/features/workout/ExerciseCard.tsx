import { type ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";

import type { SessionExercise, SessionSet, SetLogInput, ExerciseSummary } from "../../api/workout";
import type { UnitSystem } from "../../lib/units";
import type { CoachNote } from "../../api/notes";
import { PrBadge } from "../../components/PrBadge";
import { NoteThread } from "../notes/NoteThread";
import { SetEditor } from "./SetEditor";
import { describeCompact } from "./values";

export interface SetSaver {
  /** Logs one set; resolves `true` when the server accepted it. */
  (exerciseId: string, plannedExerciseId: string | null, setNo: number, input: Partial<SetLogInput>): Promise<boolean>;
}

interface Props {
  exercise: SessionExercise;
  /** Coach notes on this exercise (read-only for the athlete). */
  notes?: CoachNote[];
  athleteId?: string;
  units: UnitSystem;
  locked: boolean;
  pending: boolean;
  save: SetSaver;
  /** Called after a set was logged (not skipped), to start the rest timer. */
  onLogged: (exercise: SessionExercise) => void;
  /** Called when an added extra exercise with no logged sets is cancelled, so it can be dropped. */
  onDiscard?: (exercise: SessionExercise) => void;
}

/** Done exactly as planned: the logged values equal the targets the set was logged against. */
function isAsPlanned(set: SessionSet): boolean {
  const { log } = set;
  if (!log || log.skipped) return false;
  return log.reps === set.target_reps && log.weight_kg === set.target_weight_kg && log.seconds === set.target_seconds;
}

const ICON = { width: 20, height: 20, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 3, "aria-hidden": true } as const;

/** One set as a single non-wrapping row: number, target, check, edit (F10.6-F10.8, D95). */
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
  const target = describeCompact(
    t,
    { reps: set.target_reps, weight_kg: set.target_weight_kg, seconds: set.target_seconds },
    units,
  );
  const hasTarget = set.target_reps != null || set.target_seconds != null || set.target_weight_kg != null;
  const asPlanned = isAsPlanned(set);
  const forSet = t("workout.forSet", { exercise: exercise.exercise.name, number: set.set_no });

  const submit = async (input: Partial<SetLogInput>) => {
    const ok = await save(exercise.exercise.id, exercise.planned_exercise_id, set.set_no, input);
    if (!ok) return;
    setEditing(false);
    if (!input.skipped) onLogged(exercise);
  };

  // What the row says next to (or instead of) the target.
  let result: ReactNode = null;
  if (log?.skipped) {
    result = (
      <>
        <span aria-hidden="true">{t("workout.glyph.skipped")}</span>
        {t("workout.skipped")}
      </>
    );
  } else if (log && !asPlanned) {
    result = (
      <>
        <span aria-hidden="true">{target ? "→ " : ""}</span>
        <span className="sr-only">{t("workout.loggedPrefix")}</span>
        {describeCompact(t, log, units)}
      </>
    );
  }
  const targetText = target || (set.is_extra ? t("workout.extra") : t("workout.noTarget"));

  return (
    <li className="border-b border-line py-2">
      <div className="flex flex-nowrap items-center gap-2">
        <span className="w-7 shrink-0 text-center font-semibold tabular-nums">
          <span className="sr-only">{t("workout.setName", { number: "" })}</span>
          {set.set_no}
        </span>
        <span className="min-w-0 flex-1 truncate whitespace-nowrap text-step--1">
          <span className={result ? "text-slate" : undefined}>{targetText}</span>
          {result && (
            <>
              {" "}
              <span className="font-semibold text-spruce">{result}</span>
            </>
          )}
        </span>
        {!locked && (
          <>
            <button
              type="button"
              aria-pressed={asPlanned}
              aria-disabled={pending || !hasTarget || undefined}
              onClick={() => {
                if (!pending && hasTarget && !asPlanned) void submit({ as_planned: true });
              }}
              className={`inline-flex size-12 shrink-0 items-center justify-center rounded-md border-2 ${
                asPlanned
                  ? "border-spruce bg-spruce text-chalk"
                  : "border-iron/60 bg-transparent text-iron hover:bg-line"
              } aria-disabled:opacity-50`}
            >
              <svg {...ICON}>
                <path d="M4 12.5l5 5L20 6.5" />
              </svg>
              <span className="sr-only">
                {t("workout.asPlanned")}, {forSet}
              </span>
            </button>
            <button
              type="button"
              aria-expanded={editing}
              onClick={() => setEditing(!editing)}
              className="inline-flex size-12 shrink-0 items-center justify-center rounded-md border-2 border-iron hover:bg-line"
            >
              <svg {...ICON} strokeWidth={2}>
                <path d="M4 20h4L19 9l-4-4L4 16v4zM13 7l4 4" />
              </svg>
              <span className="sr-only">
                {t("workout.edit")} {forSet}
              </span>
            </button>
          </>
        )}
      </div>
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
          onSkip={() => void submit({ skipped: true })}
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
        {exercise.exercise.name} {exercise.is_pr && <PrBadge />}
      </h2>
      <p className="text-step--1 text-slate">{t("workout.restPlanned", { count: exercise.rest_seconds })}</p>
      {props.athleteId && (
        <NoteThread athleteId={props.athleteId} notes={props.notes ?? []} label={exercise.exercise.name} />
      )}
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
