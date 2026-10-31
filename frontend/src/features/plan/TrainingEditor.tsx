import { useDeferredValue, useEffect, useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { isApiError } from "../../api/errors";
import { useExerciseSearch, type Exercise } from "../../api/onboarding";
import { type Plan, type ProgressionRule, useSaveTraining, WEEKDAYS, type Weekday } from "../../api/plan";
import { type UnitSystem, weightUnit } from "../../lib/units";
import { BUTTON, FieldError, ICON_BUTTON, SelectInput, TextInput } from "./fields";
import { SaveBar } from "./SaveBar";
import {
  buildTrainingUpdate,
  type LocalError,
  dayPath,
  draftFromPlan,
  type DraftDay,
  type DraftExercise,
  exercisePath,
  FIELD,
  move,
  newDraftDay,
  newDraftExercise,
} from "./trainingDraft";

const RULES: ProgressionRule[] = ["linear", "double", "manual"];

export interface EditorProps {
  plan: Plan;
  athleteId: string;
  units: UnitSystem;
  /** Revision the draft was started from; sent with the save unless a conflict was reported. */
  baseRevision: number;
  conflict: boolean;
  blocked: boolean;
  onConflict: () => void;
  onSaved: (plan: Plan) => void;
  onDiscard: () => void;
  onDirtyChange: (dirty: boolean) => void;
}

function ExercisePicker({ units, onPick }: { units: UnitSystem; onPick: (e: DraftExercise) => void }) {
  const { t } = useTranslation();
  const [text, setText] = useState("");
  const inputId = useId();
  const search = useExerciseSearch(useDeferredValue(text));
  const results: Exercise[] = search.data ?? [];
  return (
    <div className="mt-3">
      <TextInput id={inputId} label={t("plan.training.addExercise")} value={text} onChange={setText} hint={t("plan.training.searchHint")} />
      {search.isSuccess && results.length === 0 && <p className="mt-1 text-step--1 text-slate">{t("plan.noResults")}</p>}
      {results.length > 0 && (
        <ul className="mt-1 flex flex-col gap-2">
          {results.map((exercise) => (
            <li key={exercise.id}>
              <button
                type="button"
                onClick={() => {
                  onPick(newDraftExercise(exercise, units));
                  setText("");
                }}
                aria-label={t("plan.training.addNamed", { name: exercise.name })}
                className={`${BUTTON} w-full text-left`}
              >
                {exercise.name}
                <span className="block text-step--1 font-normal text-slate">
                  {t(`plan.training.type.${exercise.type}`)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ExerciseCard({
  d,
  x,
  exercise,
  count,
  units,
  error,
  onChange,
  onMove,
  onRemove,
}: {
  d: number;
  x: number;
  exercise: DraftExercise;
  count: number;
  units: UnitSystem;
  error: (path: string) => string | undefined;
  onChange: (patch: Partial<DraftExercise>) => void;
  onMove: (delta: -1 | 1) => void;
  onRemove: () => void;
}) {
  const { t } = useTranslation();
  const at = (field: string) => exercisePath(d, x, field);
  const id = (field: string) => `ex-${exercise.uid}-${field}`;
  const kg = weightUnit(units);
  const timed = exercise.type === "timed";
  const own = error(exercisePath(d, x));
  return (
    <li className="border-2 border-iron/30 p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h4 className="break-words font-display text-step-1 font-bold">{exercise.name}</h4>
          <p className="text-step--1 text-slate">{t(`plan.training.type.${exercise.type}`)}</p>
        </div>
        <div className="flex shrink-0 gap-1">
          <button type="button" className={ICON_BUTTON} disabled={x === 0} onClick={() => onMove(-1)} aria-label={t("plan.training.moveExerciseUp", { name: exercise.name })}>
            <span aria-hidden="true">↑</span>
          </button>
          <button type="button" className={ICON_BUTTON} disabled={x === count - 1} onClick={() => onMove(1)} aria-label={t("plan.training.moveExerciseDown", { name: exercise.name })}>
            <span aria-hidden="true">↓</span>
          </button>
          <button type="button" className={ICON_BUTTON} onClick={onRemove} aria-label={t("plan.training.removeExercise", { name: exercise.name })}>
            <span aria-hidden="true">×</span>
          </button>
        </div>
      </div>
      {own && <FieldError id={id("error")}>{own}</FieldError>}
      <div className="mt-2 grid grid-cols-2 gap-3">
        <TextInput id={id("sets")} label={t("plan.training.sets")} value={exercise.sets} inputMode="numeric" onChange={(sets) => onChange({ sets })} error={error(at(FIELD.sets))} />
        {timed ? (
          <TextInput id={id("seconds")} label={t("plan.training.seconds")} value={exercise.seconds} inputMode="numeric" onChange={(seconds) => onChange({ seconds })} error={error(at(FIELD.seconds))} />
        ) : (
          <>
            <TextInput id={id("repsMin")} label={t("plan.training.repsMin")} value={exercise.repsMin} inputMode="numeric" onChange={(repsMin) => onChange({ repsMin })} error={error(at(FIELD.repsMin))} />
            <TextInput id={id("repsMax")} label={t("plan.training.repsMax")} value={exercise.repsMax} inputMode="numeric" onChange={(repsMax) => onChange({ repsMax })} error={error(at(FIELD.repsMax))} hint={t("plan.training.repsMaxHint")} />
            <TextInput id={id("weight")} label={t("plan.training.weight", { unit: kg })} value={exercise.weight} inputMode="decimal" onChange={(weight) => onChange({ weight })} error={error(at(FIELD.weight))} hint={t("plan.training.weightHint")} />
          </>
        )}
        <TextInput id={id("rest")} label={t("plan.training.rest")} value={exercise.rest} inputMode="numeric" onChange={(rest) => onChange({ rest })} error={error(at(FIELD.rest))} />
        <SelectInput
          id={id("rule")}
          label={t("plan.training.rule")}
          value={exercise.rule}
          onChange={(rule) => onChange({ rule: rule as ProgressionRule })}
          options={RULES.map((rule) => ({ value: rule, label: t(`plan.training.rules.${rule}`) }))}
          error={error(at(FIELD.rule))}
        />
        <TextInput id={id("increment")} label={t("plan.training.increment", { unit: kg })} value={exercise.increment} inputMode="decimal" onChange={(increment) => onChange({ increment })} error={error(at(FIELD.increment))} />
      </div>
      <label className="mt-3 flex min-h-12 items-center gap-3 font-semibold">
        <input type="checkbox" checked={exercise.deload} onChange={(event) => onChange({ deload: event.target.checked })} className="size-6" />
        {t("plan.training.deload")}
      </label>
    </li>
  );
}

/** Training days and exercises (F8): add, remove, reorder, edit every target. Saves `PUT /plan/training`. */
export function TrainingEditor({ plan, athleteId, units, baseRevision, conflict, blocked, onConflict, onSaved, onDiscard, onDirtyChange }: EditorProps) {
  const { t } = useTranslation();
  const [start] = useState(() => {
    const draft = draftFromPlan(plan.training_days, units);
    return { draft, json: JSON.stringify(draft) };
  });
  const initial = start.json;
  const [days, setDays] = useState<DraftDay[]>(start.draft);
  const [local, setLocal] = useState<Record<string, LocalError>>({});
  const [server, setServer] = useState<Record<string, string>>({});
  const save = useSaveTraining(athleteId);
  const dirty = JSON.stringify(days) !== initial;
  useEffect(() => onDirtyChange(dirty), [dirty, onDirtyChange]);

  const error = (path: string): string | undefined => (local[path] ? t(`plan.errors.${local[path]}`) : server[path]);
  const edit = (next: DraftDay[]) => {
    setDays(next);
    setLocal({});
    setServer({});
  };
  const patchDay = (d: number, patch: Partial<DraftDay>) => edit(days.map((day, i) => (i === d ? { ...day, ...patch } : day)));
  const patchExercise = (d: number, x: number, patch: Partial<DraftExercise>) =>
    patchDay(d, { exercises: days[d]!.exercises.map((e, i) => (i === x ? { ...e, ...patch } : e)) });

  const onSave = () => {
    const built = buildTrainingUpdate(days, conflict ? plan.revision : baseRevision, units);
    if (!built.body) {
      setLocal(built.errors);
      return;
    }
    save.mutate(built.body, {
      onSuccess: (next) => {
        onSaved(next);
      },
      onError: (failure) => {
        if (isApiError(failure) && failure.status === 409) onConflict();
        else if (isApiError(failure) && failure.problem.code === "invalid_plan") setServer(failure.problem.fieldErrors);
      },
    });
  };

  const failure = save.error;
  const generic = save.isError && !(isApiError(failure) && (failure.status === 409 || failure.problem.code === "invalid_plan"));
  const free = WEEKDAYS.filter((w) => !days.some((d) => d.weekday === w));

  return (
    <section aria-label={t("plan.tabs.training")}>
      {days.length === 0 && <p className="text-slate">{t("plan.training.empty")}</p>}
      <ul className="flex flex-col gap-6">
        {days.map((day, d) => {
          const heading = `day-${day.uid}`;
          return (
            <li key={day.uid} aria-labelledby={`${heading}-title`} className="border-l-4 border-plate pl-3">
              <div className="flex items-start justify-between gap-2">
                <h3 id={`${heading}-title`} className="font-display text-step-2 font-bold">
                  {t("plan.training.dayTitle", { weekday: t(`plan.weekday.${day.weekday}`), name: day.name })}
                </h3>
                <div className="flex shrink-0 gap-1">
                  <button type="button" className={ICON_BUTTON} disabled={d === 0} onClick={() => edit(move(days, d, -1))} aria-label={t("plan.training.moveDayUp", { name: day.name })}>
                    <span aria-hidden="true">↑</span>
                  </button>
                  <button type="button" className={ICON_BUTTON} disabled={d === days.length - 1} onClick={() => edit(move(days, d, 1))} aria-label={t("plan.training.moveDayDown", { name: day.name })}>
                    <span aria-hidden="true">↓</span>
                  </button>
                  <button type="button" className={ICON_BUTTON} onClick={() => edit(days.filter((_, i) => i !== d))} aria-label={t("plan.training.removeDay", { name: day.name })}>
                    <span aria-hidden="true">×</span>
                  </button>
                </div>
              </div>
              {day.editedBy && <p className="text-step--1 font-semibold text-slate">{t("plan.editedBy", { name: day.editedBy })}</p>}
              <div className="mt-2 grid grid-cols-2 gap-3">
                <SelectInput
                  id={`${heading}-weekday`}
                  label={t("plan.training.weekday")}
                  value={day.weekday}
                  onChange={(weekday) => patchDay(d, { weekday: weekday as Weekday })}
                  options={WEEKDAYS.filter((w) => w === day.weekday || free.includes(w)).map((w) => ({ value: w, label: t(`plan.weekday.${w}`) }))}
                  error={error(dayPath(d, FIELD.weekday))}
                />
                <TextInput id={`${heading}-name`} label={t("plan.training.dayName")} value={day.name} maxLength={60} onChange={(name) => patchDay(d, { name })} error={error(dayPath(d, FIELD.name))} />
              </div>
              {error(dayPath(d)) && <FieldError id={`${heading}-error`}>{error(dayPath(d))}</FieldError>}
              <ul className="mt-3 flex flex-col gap-3">
                {day.exercises.map((exercise, x) => (
                  <ExerciseCard
                    key={exercise.uid}
                    d={d}
                    x={x}
                    exercise={exercise}
                    count={day.exercises.length}
                    units={units}
                    error={error}
                    onChange={(patch) => patchExercise(d, x, patch)}
                    onMove={(delta) => patchDay(d, { exercises: move(day.exercises, x, delta) })}
                    onRemove={() => patchDay(d, { exercises: day.exercises.filter((_, i) => i !== x) })}
                  />
                ))}
              </ul>
              <ExercisePicker units={units} onPick={(e) => patchDay(d, { exercises: [...day.exercises, e] })} />
            </li>
          );
        })}
      </ul>
      <button
        type="button"
        className={`${BUTTON} mt-6`}
        disabled={free.length === 0}
        onClick={() => edit([...days, newDraftDay(free[0]!, t("plan.training.newDayName"))])}
      >
        {t("plan.training.addDay")}
      </button>
      <SaveBar dirty={dirty} pending={save.isPending} conflict={conflict} blocked={blocked} failed={generic} onSave={onSave} invalid={save.isError && isApiError(failure) && failure.problem.code === "invalid_plan"} onDiscard={onDiscard} />
    </section>
  );
}
