import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import type { ExerciseSummary, SetLogInput } from "../../api/workout";
import { kgToLb, lbToKg, parseDecimal, parseWhole, type UnitSystem, weightUnit } from "../../lib/units";
import { type Field, fieldsFor, type SetValues } from "./values";

interface Props {
  exercise: ExerciseSummary;
  /** Starting values: the logged ones, else the targets. */
  initial: Partial<SetValues>;
  units: UnitSystem;
  pending: boolean;
  onSave: (values: Pick<SetLogInput, "reps" | "weight_kg" | "seconds" | "distance_m">) => void;
  onCancel: () => void;
}

const text = (value: number | null | undefined) => (value == null ? "" : String(value));

/** Enter actual reps and weight, or duration and distance, for one set (F10). */
export function SetEditor({ exercise, initial, units, pending, onSave, onCancel }: Props) {
  const { t } = useTranslation();
  const baseId = useId();
  const fields = fieldsFor(exercise.type);
  const [draft, setDraft] = useState<Record<Field, string>>({
    reps: text(initial.reps),
    weight: text(initial.weight_kg == null ? null : units === "imperial" ? kgToLb(initial.weight_kg) : initial.weight_kg),
    seconds: text(initial.seconds),
    distance: text(initial.distance_m),
  });
  const [invalid, setInvalid] = useState<Field[]>([]);

  const submit = () => {
    if (pending) return;
    const bad: Field[] = [];
    const values: Pick<SetLogInput, "reps" | "weight_kg" | "seconds" | "distance_m"> = {};
    for (const { field, required } of fields) {
      const raw = draft[field].trim();
      if (raw === "") {
        if (required) bad.push(field);
        continue;
      }
      const parsed = field === "reps" || field === "seconds" ? parseWhole(raw) : parseDecimal(raw);
      if (parsed === null) {
        bad.push(field);
        continue;
      }
      if (field === "reps") values.reps = parsed;
      if (field === "seconds") values.seconds = parsed;
      if (field === "distance") values.distance_m = parsed;
      if (field === "weight") values.weight_kg = units === "imperial" ? lbToKg(parsed) : parsed;
    }
    setInvalid(bad);
    if (bad.length === 0) onSave(values);
  };

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
      noValidate
      className="mt-3 grid grid-cols-2 gap-3 border-l-4 border-plate pl-3"
    >
      {fields.map(({ field, required }) => {
        const id = `${baseId}-${field}`;
        const unit = field === "weight" ? weightUnit(units) : undefined;
        return (
          <div key={field}>
            <label htmlFor={id} className="block text-step--1 font-semibold">
              {t(`workout.fields.${field}`, { unit })}
              {!required && <span className="font-normal text-slate"> {t("workout.optional")}</span>}
            </label>
            <input
              id={id}
              inputMode={field === "reps" || field === "seconds" ? "numeric" : "decimal"}
              value={draft[field]}
              onChange={(event) => setDraft({ ...draft, [field]: event.target.value })}
              aria-invalid={invalid.includes(field) || undefined}
              aria-describedby={invalid.includes(field) ? `${id}-error` : undefined}
              className="mt-1 block min-h-12 w-full rounded-md border-2 border-iron/35 bg-white px-3 text-step-0"
            />
            {invalid.includes(field) && (
              <p id={`${id}-error`} role="alert" className="mt-1 text-step--1 text-alert">
                {t("workout.invalidNumber")}
              </p>
            )}
          </div>
        );
      })}
      <div className="col-span-2 flex gap-2">
        <button
          type="submit"
          aria-disabled={pending || undefined}
          className="min-h-12 rounded-md bg-spruce px-5 font-semibold text-chalk hover:bg-spruce-dark aria-disabled:opacity-75"
        >
          {t("workout.save")}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="min-h-12 rounded-md px-4 font-semibold text-spruce underline underline-offset-4"
        >
          {t("workout.cancel")}
        </button>
      </div>
    </form>
  );
}
