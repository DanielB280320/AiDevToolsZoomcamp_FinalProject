import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { isApiError } from "../../api/errors";
import {
  type AcceptOverrides,
  type ExerciseTargets,
  type Suggestion,
  useAcceptSuggestion,
  useRejectSuggestion,
} from "../../api/suggestions";
import { formatWeight, kgToLb, lbToKg, parseDecimal, parseWhole, type UnitSystem, weightUnit } from "../../lib/units";

type Field = "weight" | "repsMin" | "repsMax" | "seconds" | "kcal";

/** "6-10 reps · 42.5 kg" for whichever targets are present. */
function describeTargets(t: ReturnType<typeof useTranslation>["t"], targets: ExerciseTargets, units: UnitSystem) {
  const reps =
    targets.reps_min != null && targets.reps_max != null && targets.reps_min !== targets.reps_max
      ? t("suggestions.repRange", { min: targets.reps_min, max: targets.reps_max })
      : (targets.reps_max ?? targets.reps_min) != null
        ? t("suggestions.reps", { count: (targets.reps_max ?? targets.reps_min) as number })
        : null;
  return [
    reps,
    targets.target_seconds != null ? t("suggestions.seconds", { count: targets.target_seconds }) : null,
    targets.target_weight_kg != null ? formatWeight(targets.target_weight_kg, units) : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

function errorKey(error: unknown): "alreadyDecided" | "invalidOverrides" | "generic" {
  if (isApiError(error)) {
    if (error.problem.code === "suggestion_already_decided") return "alreadyDecided";
    if (error.problem.code === "invalid_overrides") return "invalidOverrides";
  }
  return "generic";
}

const asText = (value: number | null | undefined) => (value == null ? "" : String(value));

/** One pending suggestion: old -> new targets, the stored reason, and accept / edit / reject (F11.3, F11.4). */
export function SuggestionCard({ suggestion, units }: { suggestion: Suggestion; units: UnitSystem }) {
  const { t } = useTranslation();
  const baseId = useId();
  const accept = useAcceptSuggestion();
  const reject = useRejectSuggestion();
  const busy = accept.isPending || reject.isPending;
  const [editing, setEditing] = useState(false);
  const [invalid, setInvalid] = useState<Field[]>([]);

  const proposed = suggestion.kind === "progression" ? suggestion.payload.proposed : null;
  const [draft, setDraft] = useState<Record<Field, string>>({
    weight: asText(proposed?.target_weight_kg == null ? null : units === "imperial" ? kgToLb(proposed.target_weight_kg) : proposed.target_weight_kg),
    repsMin: asText(proposed?.reps_min),
    repsMax: asText(proposed?.reps_max),
    seconds: asText(proposed?.target_seconds),
    kcal: asText(suggestion.kind === "calories" ? suggestion.payload.proposed_kcal : null),
  });

  const editable = suggestion.kind === "progression" || suggestion.kind === "calories";
  const fields: Field[] =
    suggestion.kind === "calories"
      ? ["kcal"]
      : proposed
        ? ([
            proposed.target_weight_kg != null && "weight",
            proposed.reps_min != null && "repsMin",
            proposed.reps_max != null && "repsMax",
            proposed.target_seconds != null && "seconds",
          ].filter(Boolean) as Field[])
        : [];

  let change: string;
  let title: string;
  if (suggestion.kind === "progression") {
    title = suggestion.payload.exercise.name;
    change = `${describeTargets(t, suggestion.payload.current, units)} → ${describeTargets(t, suggestion.payload.proposed, units)}`;
  } else if (suggestion.kind === "calories") {
    title = t("suggestions.kind.calories");
    change = `${t("suggestions.kcal", { count: suggestion.payload.current_kcal })} → ${t("suggestions.kcal", { count: suggestion.payload.proposed_kcal })}`;
  } else {
    title = t("suggestions.kind.recalc");
    change = `${t("suggestions.kcal", { count: suggestion.payload.current.kcal })} → ${t("suggestions.kcal", { count: suggestion.payload.proposed.kcal })}`;
  }

  const submitEdit = () => {
    if (busy) return;
    const bad: Field[] = [];
    const overrides: AcceptOverrides = {};
    for (const field of fields) {
      const raw = draft[field].trim();
      const parsed = field === "weight" ? parseDecimal(raw) : parseWhole(raw);
      if (parsed === null) {
        bad.push(field);
        continue;
      }
      if (field === "weight") overrides.target_weight_kg = units === "imperial" ? lbToKg(parsed) : parsed;
      if (field === "repsMin") overrides.reps_min = parsed;
      if (field === "repsMax") overrides.reps_max = parsed;
      if (field === "seconds") overrides.target_seconds = parsed;
      if (field === "kcal") overrides.kcal = parsed;
    }
    setInvalid(bad);
    if (bad.length === 0) accept.mutate({ id: suggestion.id, overrides });
  };

  const label = (field: Field) =>
    field === "weight" ? t("suggestions.field.weight", { unit: weightUnit(units) }) : t(`suggestions.field.${field}`);
  const error = accept.error ?? reject.error;

  return (
    <li className="border-b border-line py-3" data-testid="suggestion">
      <p className="font-semibold">{title}</p>
      <p className="mt-1 font-display text-step-1 font-bold" aria-label={t("suggestions.change")}>
        {change}
      </p>
      <p className="mt-1 text-step--1 text-slate">{suggestion.reason}</p>
      {error && (
        <p role="alert" className="mt-2 border-l-4 border-alert pl-3 text-alert">
          {t(`suggestions.errors.${errorKey(error)}`)}
        </p>
      )}
      {editing ? (
        <form
          className="mt-3 flex flex-wrap items-end gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            submitEdit();
          }}
        >
          {fields.map((field) => (
            <div key={field} className="flex flex-col">
              <label htmlFor={`${baseId}-${field}`} className="text-step--1 font-semibold">
                {label(field)}
              </label>
              <input
                id={`${baseId}-${field}`}
                inputMode="decimal"
                value={draft[field]}
                aria-invalid={invalid.includes(field) || undefined}
                onChange={(event) => setDraft({ ...draft, [field]: event.target.value })}
                className="min-h-12 w-28 rounded-md border-2 border-iron px-2"
              />
            </div>
          ))}
          {invalid.length > 0 && (
            <p role="alert" className="w-full text-alert">
              {t("suggestions.errors.invalidNumber")}
            </p>
          )}
          <button
            type="submit"
            aria-disabled={busy || undefined}
            className="min-h-12 rounded-md bg-spruce px-4 font-semibold text-chalk hover:bg-spruce-dark"
          >
            {t("suggestions.saveAccept")}
          </button>
          <button type="button" onClick={() => setEditing(false)} className="min-h-12 rounded-md border-2 border-iron px-4 font-semibold hover:bg-line">
            {t("suggestions.cancel")}
          </button>
        </form>
      ) : (
        <div className="mt-3 flex flex-wrap gap-3">
          <button
            type="button"
            aria-disabled={busy || undefined}
            onClick={() => !busy && accept.mutate({ id: suggestion.id })}
            className="min-h-12 rounded-md bg-spruce px-4 font-semibold text-chalk hover:bg-spruce-dark"
          >
            {t("suggestions.accept")}
          </button>
          {editable && (
            <button type="button" onClick={() => setEditing(true)} className="min-h-12 rounded-md border-2 border-iron px-4 font-semibold hover:bg-line">
              {t("suggestions.edit")}
            </button>
          )}
          <button
            type="button"
            aria-disabled={busy || undefined}
            onClick={() => !busy && reject.mutate(suggestion.id)}
            className="min-h-12 rounded-md border-2 border-iron px-4 font-semibold hover:bg-line"
          >
            {t("suggestions.reject")}
          </button>
        </div>
      )}
    </li>
  );
}
