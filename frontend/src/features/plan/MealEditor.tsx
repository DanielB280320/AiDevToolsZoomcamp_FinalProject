import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { MealSlot } from "../../api/meals";
import { isApiError } from "../../api/errors";
import { useSaveMeals, type MealDay, type Weekday } from "../../api/plan";
import { BUTTON, FieldError, ICON_BUTTON, SelectInput, TextInput } from "./fields";
import { MealPicker, SLOTS } from "./MealPicker";
import { buildMealUpdate, draftFromLibraryMeal, mealDraftFromPlan, mealPath, requestIndex, type DraftMeal, type DraftMealDay } from "./mealDraft";
import { FIELD, type LocalError } from "./trainingDraft";
import { SaveBar } from "./SaveBar";
import type { EditorProps } from "./TrainingEditor";

const DEFAULT_SLOT: MealSlot = "lunch";
const pickerSlot = (day: DraftMealDay, replace: string | null): MealSlot =>
  day.meals.find((m) => m.uid === replace)?.slot ?? DEFAULT_SLOT;

type Picker = { weekday: Weekday; replace: string | null } | null;

/** Meals per day and slot (F8): add, replace, remove, edit grams and portion. Saves `PUT /plan/meals`. */
export function MealEditor({ plan, athleteId, baseRevision, conflict, blocked, onConflict, onSaved, onDiscard, onDirtyChange }: Omit<EditorProps, "units">) {
  const { t } = useTranslation();
  const [start] = useState(() => {
    const draft = mealDraftFromPlan(plan.meal_days);
    return { draft, json: JSON.stringify(draft) };
  });
  const initial = start.json;
  const [days, setDays] = useState<DraftMealDay[]>(start.draft);
  const [local, setLocal] = useState<Record<string, LocalError>>({});
  const [server, setServer] = useState<Record<string, string>>({});
  const [picker, setPicker] = useState<Picker>(null);
  const save = useSaveMeals(athleteId);
  const dirty = JSON.stringify(days) !== initial;
  useEffect(() => onDirtyChange(dirty), [dirty, onDirtyChange]);

  const error = (path: string): string | undefined => (local[path] ? t(`plan.errors.${local[path]}`) : server[path]);
  const edit = (next: DraftMealDay[]) => {
    setDays(next);
    setLocal({});
    setServer({});
  };
  const patchMeal = (weekday: Weekday, uid: string, patch: Partial<DraftMeal>) =>
    edit(days.map((day) => (day.weekday === weekday ? { ...day, meals: day.meals.map((m) => (m.uid === uid ? { ...m, ...patch } : m)) } : day)));

  const onSave = () => {
    const built = buildMealUpdate(days, conflict ? plan.revision : baseRevision);
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
  const invalid = save.isError && isApiError(failure) && failure.problem.code === "invalid_plan";
  const generic = save.isError && !(isApiError(failure) && (failure.status === 409 || invalid));

  return (
    <section aria-label={t("plan.tabs.meals")}>
      <ul className="flex flex-col gap-6">
        {days.map((day) => {
          const d = requestIndex(days, day.weekday);
          const title = `meal-day-${day.weekday}`;
          const open = picker?.weekday === day.weekday ? picker : null;
          const warning = plan.meal_days.find((m: MealDay) => m.weekday === day.weekday)?.warning;
          return (
            <li key={day.uid} aria-labelledby={`${title}-title`} className="border-l-4 border-plate pl-3">
              <h3 id={`${title}-title`} className="font-display text-step-2 font-bold">
                {t(`plan.weekdayLong.${day.weekday}`)}
              </h3>
              {day.editedBy && <p className="text-step--1 font-semibold text-slate">{t("plan.editedBy", { name: day.editedBy })}</p>}
              {warning && <p className="text-step--1 text-slate">{warning}</p>}
              {day.meals.length === 0 && <p className="text-slate">{t("plan.meals.empty")}</p>}
              <ul className="mt-2 flex flex-col gap-3">
                {day.meals.map((meal, j) => {
                  const id = (f: string) => `meal-${meal.uid}-${f}`;
                  return (
                    <li key={meal.uid} className="border-2 border-iron/30 p-3">
                      <div className="flex items-start justify-between gap-2">
                        <h4 className="min-w-0 break-words font-display text-step-1 font-bold">{meal.mealName}</h4>
                        <button type="button" className={ICON_BUTTON} onClick={() => edit(days.map((x) => (x.weekday === day.weekday ? { ...x, meals: x.meals.filter((m) => m.uid !== meal.uid) } : x)))} aria-label={t("plan.meals.remove", { name: meal.mealName })}>
                          <span aria-hidden="true">×</span>
                        </button>
                      </div>
                      <div className="mt-2 grid grid-cols-2 gap-3">
                        <SelectInput id={id("slot")} label={t("plan.meals.slot")} value={meal.slot} onChange={(slot) => patchMeal(day.weekday, meal.uid, { slot: slot as DraftMeal["slot"] })} options={SLOTS.map((s) => ({ value: s, label: t(`plan.slot.${s}`) }))} error={error(mealPath(d, j, FIELD.slot))} />
                        <TextInput
                          id={id("portion")}
                          label={t("plan.meals.portion")}
                          value={meal.gramsEdited ? "1" : meal.portion}
                          disabled={meal.gramsEdited}
                          inputMode="decimal"
                          onChange={(portion) => patchMeal(day.weekday, meal.uid, { portion })}
                          error={error(mealPath(d, j, FIELD.portion))}
                          hint={meal.gramsEdited ? t("plan.meals.portionLocked") : t("plan.meals.portionHint")}
                        />
                      </div>
                      {error(mealPath(d, j)) && <FieldError id={id("error")}>{error(mealPath(d, j))}</FieldError>}
                      <ul className="mt-2 flex flex-col gap-2">
                        {meal.foods.map((food, k) => (
                          <li key={food.foodId} className="grid grid-cols-[1fr_7rem] items-end gap-3">
                            <span className="break-words">{food.name}</span>
                            <TextInput
                              id={id(`grams-${k}`)}
                              label={t("plan.meals.gramsOf", { name: food.name })}
                              value={food.grams}
                              inputMode="decimal"
                              onChange={(grams) => patchMeal(day.weekday, meal.uid, { gramsEdited: true, foods: meal.foods.map((f, i) => (i === k ? { ...f, grams } : f)) })}
                              error={error(mealPath(d, j, `items[${k}].grams`))}
                            />
                          </li>
                        ))}
                      </ul>
                      <button type="button" className={`${BUTTON} mt-3`} onClick={() => setPicker({ weekday: day.weekday, replace: meal.uid })} aria-label={t("plan.meals.replace", { name: meal.mealName })}>
                        {t("plan.meals.replaceButton")}
                      </button>
                    </li>
                  );
                })}
              </ul>
              {open ? (
                <MealPicker
                  slot={pickerSlot(day, open.replace)}
                  askSlot={open.replace === null}
                  onCancel={() => setPicker(null)}
                  onPick={(meal, slot) => {
                    const target = open.replace ? day.meals.find((m) => m.uid === open.replace) : undefined;
                    const fresh = draftFromLibraryMeal(meal, target?.slot ?? slot, target?.gramsEdited ? "1" : target?.portion ?? "1", target?.id);
                    edit(days.map((x) => (x.weekday === day.weekday ? { ...x, meals: target ? x.meals.map((m) => (m.uid === target.uid ? fresh : m)) : [...x.meals, fresh] } : x)));
                    setPicker(null);
                  }}
                />
              ) : (
                <button type="button" className={`${BUTTON} mt-3`} onClick={() => setPicker({ weekday: day.weekday, replace: null })} aria-label={t("plan.meals.addTo", { weekday: t(`plan.weekdayLong.${day.weekday}`) })}>
                  {t("plan.meals.add")}
                </button>
              )}
            </li>
          );
        })}
      </ul>
      <SaveBar dirty={dirty} pending={save.isPending} conflict={conflict} blocked={blocked} failed={generic} invalid={invalid} onSave={onSave} onDiscard={onDiscard} />
    </section>
  );
}
