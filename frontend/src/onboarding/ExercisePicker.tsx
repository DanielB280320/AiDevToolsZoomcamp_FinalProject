import { useDeferredValue, useState } from "react";
import { useTranslation } from "react-i18next";

import { useExerciseSearch } from "../api/onboarding";

interface Props {
  selected: { id: string; name: string }[];
  onChange: (selected: { id: string; name: string }[]) => void;
}

/** Searches the exercise catalog by name and keeps the chosen exercises as removable chips. */
export function ExercisePicker({ selected, onChange }: Props) {
  const { t } = useTranslation();
  const [text, setText] = useState("");
  const search = useExerciseSearch(useDeferredValue(text));
  const chosen = new Set(selected.map((exercise) => exercise.id));
  const results = (search.data ?? []).filter((exercise) => !chosen.has(exercise.id));

  return (
    <fieldset>
      <legend className="font-semibold">{t("onboarding.training.avoid.legend")}</legend>
      <p id="avoid-hint" className="mt-1 text-step--1 text-slate">
        {t("onboarding.training.avoid.hint")}
      </p>

      {selected.length > 0 && (
        <ul aria-label={t("onboarding.training.avoid.selected")} className="mt-2 flex flex-wrap gap-2">
          {selected.map((exercise) => (
            <li key={exercise.id}>
              <button
                type="button"
                onClick={() => onChange(selected.filter((item) => item.id !== exercise.id))}
                aria-label={t("onboarding.training.avoid.remove", { name: exercise.name })}
                className="min-h-12 rounded-md bg-iron px-3 py-2 font-semibold text-chalk"
              >
                {exercise.name} <span aria-hidden="true">×</span>
              </button>
            </li>
          ))}
        </ul>
      )}

      <label htmlFor="avoid-search" className="mt-3 block font-semibold">
        {t("onboarding.training.avoid.searchLabel")}
      </label>
      <input
        id="avoid-search"
        type="search"
        value={text}
        onChange={(event) => setText(event.target.value)}
        aria-describedby="avoid-hint"
        autoComplete="off"
        maxLength={100}
        className="mt-1.5 block min-h-12 w-full rounded-md border-2 border-iron/35 bg-white px-3 py-2 text-step-0 text-iron hover:border-iron/60"
      />
      <div aria-live="polite" className="mt-2">
        {search.isFetching && <p className="text-step--1 text-slate">{t("onboarding.training.avoid.searching")}</p>}
        {search.isError && <p className="text-step--1 font-semibold text-alert">{t("onboarding.training.avoid.searchFailed")}</p>}
        {search.isSuccess && !search.isFetching && results.length === 0 && (
          <p className="text-step--1 text-slate">{t("onboarding.training.avoid.noResults")}</p>
        )}
      </div>
      {results.length > 0 && (
        <ul className="mt-1 flex flex-col gap-2">
          {results.map((exercise) => (
            <li key={exercise.id}>
              <button
                type="button"
                onClick={() => onChange([...selected, { id: exercise.id, name: exercise.name }])}
                aria-label={t("onboarding.training.avoid.add", { name: exercise.name })}
                className="min-h-12 w-full rounded-md border-2 border-iron/35 bg-white px-3 py-2 text-left hover:border-iron/60"
              >
                {exercise.name}
              </button>
            </li>
          ))}
        </ul>
      )}
    </fieldset>
  );
}
