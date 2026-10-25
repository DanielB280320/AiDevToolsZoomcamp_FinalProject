import { useDeferredValue, useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { useExerciseSearch } from "../../api/onboarding";
import type { ExerciseSummary } from "../../api/workout";

/** Adds an exercise that is not in the plan (F10): search the catalog by name, then log its first set. */
export function ExerciseAdder({ onPick }: { onPick: (exercise: ExerciseSummary) => void }) {
  const { t } = useTranslation();
  const id = useId();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const search = useExerciseSearch(useDeferredValue(text));

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="mt-6 min-h-12 rounded-md border-2 border-iron px-4 font-semibold hover:bg-line"
      >
        {t("workout.addExercise")}
      </button>
    );
  }
  return (
    <div className="mt-6 border-l-4 border-plate pl-3">
      <label htmlFor={id} className="block font-semibold">
        {t("workout.searchExercise")}
      </label>
      <input
        id={id}
        type="search"
        value={text}
        onChange={(event) => setText(event.target.value)}
        autoComplete="off"
        maxLength={100}
        className="mt-1 block min-h-12 w-full rounded-md border-2 border-iron/35 bg-white px-3"
      />
      <ul className="mt-2">
        {(search.data ?? []).map((exercise) => (
          <li key={exercise.id}>
            <button
              type="button"
              onClick={() => {
                onPick(exercise);
                setOpen(false);
                setText("");
              }}
              className="min-h-12 w-full border-b border-line py-2 text-left font-semibold hover:bg-line"
            >
              {exercise.name}
            </button>
          </li>
        ))}
      </ul>
      <button
        type="button"
        onClick={() => setOpen(false)}
        className="mt-2 min-h-12 px-4 font-semibold text-spruce underline underline-offset-4"
      >
        {t("workout.cancel")}
      </button>
    </div>
  );
}
