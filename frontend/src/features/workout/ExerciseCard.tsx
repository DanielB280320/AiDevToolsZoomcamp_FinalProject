import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import type { SessionExercise, SessionSet, SetLogInput, ExerciseSummary } from "../../api/workout";
import type { UnitSystem } from "../../lib/units";
import type { CoachNote } from "../../api/notes";
import { PrBadge } from "../../components/PrBadge";
import { NoteThread } from "../notes/NoteThread";
import { SetEditor } from "./SetEditor";
import { canLogAsPlanned, cardLines, describeCompact } from "./values";

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

/** One set as a compact card: number, target (or logged) values, check, edit (F10.6-F10.8, D96). */
function SetCard({
  exercise,
  set,
  units,
  locked,
  pending,
  editing,
  onCheck,
  onToggleEdit,
}: {
  exercise: SessionExercise;
  set: SessionSet;
  units: UnitSystem;
  locked: boolean;
  pending: boolean;
  editing: boolean;
  onCheck: () => void;
  onToggleEdit: (open?: boolean) => void;
}) {
  const { t } = useTranslation();
  const { log } = set;
  const type = exercise.exercise.type;
  const planned = {
    reps: set.target_reps,
    weight_kg: set.target_weight_kg,
    seconds: set.target_seconds,
    distance_m: null,
  };
  const hasTarget = set.target_reps != null || set.target_seconds != null || set.target_weight_kg != null;
  // A strength set without a planned weight is not logged by the check: it opens the editor (D96).
  const needsEntry = type === "strength" && set.target_weight_kg == null;
  const canCheck = canLogAsPlanned(set, type) || needsEntry;
  const asPlanned = isAsPlanned(set);
  const forSet = t("workout.forSet", { exercise: exercise.exercise.name, number: set.set_no });
  // The logged values once the set was logged (or changed with edit), otherwise the plan's target.
  const shown = log && !log.skipped ? log : planned;
  const lines = cardLines(t, shown, units, type);
  const plannedLines = cardLines(t, planned, units, type);
  const plannedText =
    planned.weight_kg != null ? describeCompact(t, planned, units) : plannedLines.main;
  const edited = log != null && !log.skipped && !asPlanned;
  const main = lines.main || (set.is_extra ? t("workout.extra") : t("workout.noTarget"));

  return (
    <li
      data-testid="set-card"
      className={`flex min-w-[8.5rem] flex-1 basis-[8.5rem] flex-col gap-1 rounded-md border-2 p-2 ${
        asPlanned ? "border-spruce" : "border-line"
      }`}
    >
      <span className="text-step--1 font-semibold text-slate">
        {t("workout.setName", { number: set.set_no })}
      </span>
      <span className="break-words font-semibold tabular-nums">
        {edited && <span className="sr-only">{t("workout.loggedPrefix")} </span>}
        {main}
      </span>
      {lines.weight && <span className="break-words text-step--1">{lines.weight}</span>}
      {log?.skipped && (
        <span className="text-step--1 font-semibold text-spruce">
          <span aria-hidden="true">{t("workout.glyph.skipped")}</span>
          {t("workout.skipped")}
        </span>
      )}
      {edited && hasTarget && (
        <span className="text-step--1 text-slate">
          {t("workout.plannedValues", { values: plannedText })}
        </span>
      )}
      {!locked && (
        <div className="mt-auto flex gap-2 pt-1">
          <button
            type="button"
            aria-pressed={asPlanned}
            aria-disabled={pending || !canCheck || undefined}
            onClick={() => {
              if (pending || !canCheck || asPlanned) return;
              if (needsEntry) onToggleEdit(true);
              else onCheck();
            }}
            className={`inline-flex size-11 shrink-0 items-center justify-center rounded-md border-2 ${
              asPlanned ? "border-spruce bg-spruce text-chalk" : "border-iron/60 bg-transparent text-iron hover:bg-line"
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
            onClick={() => onToggleEdit()}
            className="inline-flex size-11 shrink-0 items-center justify-center rounded-md border-2 border-iron hover:bg-line"
          >
            <svg {...ICON} strokeWidth={2}>
              <path d="M4 20h4L19 9l-4-4L4 16v4zM13 7l4 4" />
            </svg>
            <span className="sr-only">
              {t("workout.edit")} {forSet}
            </span>
          </button>
        </div>
      )}
    </li>
  );
}

/** One exercise of the session as a collapsible section: its set cards, plus "Add set" for extras. */
export function ExerciseCard(props: Props & { defaultOpen?: boolean }) {
  const { t } = useTranslation();
  const { exercise, locked, save, onLogged } = props;
  const [open, setOpen] = useState(props.defaultOpen ?? false);
  const [adding, setAdding] = useState(false);
  const [editingNo, setEditingNo] = useState<number | null>(null);
  const panelId = useId();
  const nextSetNo = exercise.sets.reduce((max, s) => Math.max(max, s.set_no), 0) + 1;
  const logged = exercise.sets.filter((s) => s.log != null).length;
  const editingSet = exercise.sets.find((s) => s.set_no === editingNo);

  // An extra exercise has no sets until the first is logged: open the editor straight away.
  const showEditor = adding || (exercise.is_extra && exercise.sets.length === 0 && !locked);

  const submit = async (set: SessionSet, input: Partial<SetLogInput>) => {
    const ok = await save(exercise.exercise.id, exercise.planned_exercise_id, set.set_no, input);
    if (!ok) return;
    setEditingNo(null);
    if (!input.skipped) onLogged(exercise);
  };

  return (
    <section aria-labelledby={`ex-${exercise.exercise.id}`} className="mt-6 border-t-4 border-iron pt-3">
      <h2 id={`ex-${exercise.exercise.id}`} className="font-display text-step-2 font-bold">
        <button
          type="button"
          aria-expanded={open}
          aria-controls={panelId}
          onClick={() => setOpen(!open)}
          className="flex min-h-12 w-full items-center gap-2 text-left"
        >
          <svg
            width="20"
            height="20"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="3"
            aria-hidden="true"
            className={`shrink-0 transition-transform ${open ? "rotate-90" : ""}`}
          >
            <path d="M9 5l7 7-7 7" />
          </svg>
          <span className="min-w-0 flex-1">
            {exercise.exercise.name} {exercise.is_pr && <PrBadge />}
          </span>
          <span className="shrink-0 text-step--1 font-normal text-slate">
            {t("workout.setsLogged", { logged, total: exercise.sets.length })}
          </span>
        </button>
      </h2>
      <div id={panelId} hidden={!open}>
        <p className="text-step--1 text-slate">{t("workout.restPlanned", { count: exercise.rest_seconds })}</p>
        {props.athleteId && (
          <NoteThread athleteId={props.athleteId} notes={props.notes ?? []} label={exercise.exercise.name} />
        )}
        <ul className="mt-2 flex flex-wrap gap-2">
          {exercise.sets.map((set) => (
            <SetCard
              key={set.set_no}
              exercise={exercise}
              set={set}
              units={props.units}
              locked={locked}
              pending={props.pending}
              editing={editingNo === set.set_no}
              onCheck={() => void submit(set, { as_planned: true })}
              onToggleEdit={(forceOpen) =>
                setEditingNo(editingNo === set.set_no && !forceOpen ? null : set.set_no)
              }
            />
          ))}
        </ul>
        {editingSet && !locked && (
          <SetEditor
            key={editingSet.set_no}
            exercise={exercise.exercise}
            initial={{
              reps: editingSet.log?.reps ?? editingSet.target_reps,
              weight_kg: editingSet.log?.weight_kg ?? editingSet.target_weight_kg,
              seconds: editingSet.log?.seconds ?? editingSet.target_seconds,
              distance_m: editingSet.log?.distance_m ?? null,
            }}
            units={props.units}
            pending={props.pending}
            onSave={(values) => void submit(editingSet, values)}
            onCancel={() => setEditingNo(null)}
            onSkip={() => void submit(editingSet, { skipped: true })}
          />
        )}
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
      </div>
    </section>
  );
}

export type { ExerciseSummary };
