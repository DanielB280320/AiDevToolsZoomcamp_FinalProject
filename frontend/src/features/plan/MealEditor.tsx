import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { MealSlot } from "../../api/meals";
import { isApiError } from "../../api/errors";
import {
  useSaveMeals,
  type MealDay,
  type MealSwap,
  type Weekday,
} from "../../api/plan";
import {
  BUTTON,
  FieldError,
  ICON_BUTTON,
  SelectInput,
  TextInput,
} from "./fields";
import { DayRow } from "./DayRow";
import { DuplicateDay } from "./DuplicateDay";
import { MealPicker, SLOTS } from "./MealPicker";
import { MealSwaps } from "./MealSwaps";
import { buildMealUpdate, draftFromLibraryMeal, mealKcal, draftFromSwap, duplicateMealDay, mealDraftFromPlan, mealPath, requestIndex, type DraftMeal, type DraftMealDay } from "./mealDraft";
import { FIELD, type LocalError } from "./trainingDraft";
import { SaveBar } from "./SaveBar";
import type { EditorProps } from "./TrainingEditor";
import { ChevronDownIcon } from "../../components/icons";
import { Collapse, ITEM } from "../../components/card";

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
  const [swapping, setSwapping] = useState<string | null>(null);
  // Days are collapsed by default; a day opens when it has an error or content was copied into it (D105).
  const [open, setOpen] = useState<ReadonlySet<Weekday>>(() => new Set());
  // Foods and grams of a meal are folded away by default; a meal opens when one of its grams has an error.
  const [openMeals, setOpenMeals] = useState<ReadonlySet<string>>(() => new Set());
  const toggleMeal = (uid: string) =>
    setOpenMeals((was) => {
      const next = new Set(was);
      if (!next.delete(uid)) next.add(uid);
      return next;
    });
  const save = useSaveMeals(athleteId);
  const dirty = JSON.stringify(days) !== initial;
  useEffect(() => onDirtyChange(dirty), [dirty, onDirtyChange]);

  const openDays = (weekdays: Weekday[]) =>
    setOpen((was) => new Set([...was, ...weekdays]));
  const openWithErrors = (
    draft: DraftMealDay[],
    errors: Record<string, unknown>,
  ) => {
    const withGrams = draft.flatMap((day) => {
      const i = requestIndex(draft, day.weekday);
      return day.meals.filter((_, j) => Object.keys(errors).some((path) => path.startsWith(`${mealPath(i, j)}.items`))).map((m) => m.uid);
    });
    if (withGrams.length > 0) setOpenMeals((was) => new Set([...was, ...withGrams]));
    openDays(
      draft
        .filter(
          (day) =>
            requestIndex(draft, day.weekday) >= 0 &&
            Object.keys(errors).some((path) =>
              path.startsWith(`meal_days[${requestIndex(draft, day.weekday)}]`),
            ),
        )
        .map((day) => day.weekday),
    );
  };
  const error = (path: string): string | undefined =>
    local[path] ? t(`plan.errors.${local[path]}`) : server[path];
  const edit = (next: DraftMealDay[]) => {
    setDays(next);
    setLocal({});
    setServer({});
  };
  const patchMeal = (weekday: Weekday, uid: string, patch: Partial<DraftMeal>) =>
    edit(days.map((day) => (day.weekday === weekday ? { ...day, meals: day.meals.map((m) => (m.uid === uid ? { ...m, ...patch } : m)) } : day)));

  const submit = (draft: DraftMealDay[]) => {
    const built = buildMealUpdate(draft, conflict ? plan.revision : baseRevision);
    if (!built.body) {
      setLocal(built.errors);
      openWithErrors(draft, built.errors);
      return;
    }
    save.mutate(built.body, {
      onSuccess: (next) => {
        onSaved(next);
      },
      onError: (failure) => {
        if (isApiError(failure) && failure.status === 409) onConflict();
        else if (
          isApiError(failure) &&
          failure.problem.code === "invalid_plan"
        ) {
          setServer(failure.problem.fieldErrors);
          openWithErrors(draft, failure.problem.fieldErrors);
        }
      },
    });
  };
  const onSave = () => submit(days);
  /** Choosing a swap replaces the meal with a new one (D73) and saves right away, like any other edit. */
  const applySwap = (weekday: Weekday, uid: string, swap: MealSwap) => {
    const next = days.map((day) =>
      day.weekday === weekday ? { ...day, editedBy: null, meals: day.meals.map((m) => (m.uid === uid ? draftFromSwap(swap, m.slot) : m)) } : day,
    );
    setSwapping(null);
    edit(next);
    submit(next);
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
          const hintId = `${title}-hint`;
          const pick = picker?.weekday === day.weekday ? picker : null;
          const warning = plan.meal_days.find(
            (m: MealDay) => m.weekday === day.weekday,
          )?.warning;
          return (
            <DayRow
              key={day.uid}
              id={title}
              open={open.has(day.weekday)}
              onToggle={() =>
                setOpen(
                  (was) =>
                    new Set(
                      was.has(day.weekday)
                        ? [...was].filter((w) => w !== day.weekday)
                        : [...was, day.weekday],
                    ),
                )
              }
              title={t(`plan.weekdayLong.${day.weekday}`)}
              summary={
                day.meals.length === 0
                  ? t("plan.days.noMeals")
                  : t("plan.days.meals", { count: day.meals.length })
              }
              note={
                day.editedBy ? (
                  <p className="text-step--1 font-semibold text-slate">
                    {t("plan.editedBy", { name: day.editedBy })}
                  </p>
                ) : null
              }
            >
              {warning && <p className="text-step--1 text-slate">{warning}</p>}
              {day.meals.length > 0 && (
                <p id={hintId} className="text-step--1 text-slate">
                  {t("plan.meals.portionHint")}
                </p>
              )}
              {day.meals.length === 0 && <p className="text-slate">{t("plan.meals.empty")}</p>}
              <ul className="mt-2 flex flex-col gap-3">
                {day.meals.map((meal, j) => {
                  const id = (f: string) => `meal-${meal.uid}-${f}`;
                  const summary = t("plan.meals.foodsSummary", { count: meal.foods.length, kcal: mealKcal(meal.foods) });
                  return (
                    <li key={meal.uid} className={ITEM}>
                      <div className="flex flex-wrap items-end gap-x-2 gap-y-2" data-testid="meal-row">
                        <h4 className="min-w-0 flex-1 basis-full break-words font-display text-step-1 font-semibold sm:basis-0">{meal.mealName}</h4>
                        <div className="w-32 shrink-0 grow sm:w-36 sm:grow-0">
                          <SelectInput compact describedBy={hintId} id={id("slot")} label={t("plan.meals.slot")} value={meal.slot} onChange={(slot) => patchMeal(day.weekday, meal.uid, { slot: slot as DraftMeal["slot"] })} options={SLOTS.map((s) => ({ value: s, label: t(`plan.slot.${s}`) }))} error={error(mealPath(d, j, FIELD.slot))} />
                        </div>
                        <div className="w-24 shrink-0">
                          <TextInput
                            compact
                            describedBy={hintId}
                            id={id("portion")}
                            label={t("plan.meals.portion")}
                            value={meal.gramsEdited ? "1" : meal.portion}
                            disabled={meal.gramsEdited}
                            inputMode="decimal"
                            onChange={(portion) => patchMeal(day.weekday, meal.uid, { portion })}
                            error={error(mealPath(d, j, FIELD.portion))}
                          />
                        </div>
                        <button type="button" className={ICON_BUTTON} onClick={() => edit(days.map((x) => (x.weekday === day.weekday ? { ...x, meals: x.meals.filter((m) => m.uid !== meal.uid) } : x)))} aria-label={t("plan.meals.remove", { name: meal.mealName })}>
                          <span aria-hidden="true">×</span>
                        </button>
                      </div>
                      {meal.gramsEdited && <p className="mt-1 text-step--1 text-slate">{t("plan.meals.portionLocked")}</p>}
                      {error(mealPath(d, j)) && <FieldError id={id("error")}>{error(mealPath(d, j))}</FieldError>}
                      <button
                        type="button"
                        id={id("toggle")}
                        aria-expanded={openMeals.has(meal.uid)}
                        aria-controls={id("content")}
                        aria-label={t("plan.meals.foodsToggle", { name: meal.mealName, summary })}
                        onClick={() => toggleMeal(meal.uid)}
                        className="mt-1 flex min-h-11 items-center gap-2 text-left text-step--1 font-semibold text-spruce hover:underline"
                      >
                        <ChevronDownIcon className={`size-5 transition-transform ${openMeals.has(meal.uid) ? "rotate-180" : ""}`} />
                        <span>{summary}</span>
                      </button>
                      <Collapse id={id("content")} open={openMeals.has(meal.uid)}>
                        <ul className="mt-1 flex flex-col">
                          {meal.foods.map((food, k) => (
                            <li key={food.foodId} className="flex items-start justify-between gap-3 border-b border-line py-1">
                              <span className="min-w-0 flex-1 break-words pt-2">{food.name}</span>
                              <div className="w-28 shrink-0">
                                <TextInput
                                  compact
                                  labelHidden
                                  id={id(`grams-${k}`)}
                                  label={t("plan.meals.gramsOf", { name: food.name })}
                                  value={food.grams}
                                  inputMode="decimal"
                                  onChange={(grams) => patchMeal(day.weekday, meal.uid, { gramsEdited: true, foods: meal.foods.map((f, i) => (i === k ? { ...f, grams } : f)) })}
                                  error={error(mealPath(d, j, `items[${k}].grams`))}
                                />
                              </div>
                              <span aria-hidden="true" className="w-3 shrink-0 pt-2 text-step--1 text-slate">{t("plan.meals.unitG")}</span>
                            </li>
                          ))}
                        </ul>
                        <div className="mt-2 flex flex-wrap gap-2">
                          <button type="button" className={BUTTON} onClick={() => setPicker({ weekday: day.weekday, replace: meal.uid })} aria-label={t("plan.meals.replace", { name: meal.mealName })}>
                            {t("plan.meals.replaceButton")}
                          </button>
                          {meal.mealKey && (
                            <button type="button" className={BUTTON} disabled={dirty || blocked || save.isPending} aria-expanded={swapping === meal.uid} onClick={() => setSwapping(swapping === meal.uid ? null : meal.uid)} aria-label={t("plan.meals.swap.open", { name: meal.mealName })}>
                              {t("plan.meals.swap.button")}
                            </button>
                          )}
                        </div>
                        {meal.mealKey && dirty && <p className="mt-1 text-step--1 text-slate">{t("plan.meals.swap.saveFirst")}</p>}
                        {meal.mealKey && swapping === meal.uid && !dirty && (
                          <MealSwaps athleteId={athleteId} mealKey={meal.mealKey} mealName={meal.mealName} pending={save.isPending} onPick={(swap) => applySwap(day.weekday, meal.uid, swap)} onClose={() => setSwapping(null)} />
                        )}
                      </Collapse>
                    </li>
                  );
                })}
              </ul>
              <DuplicateDay
                idPrefix={title}
                from={day.weekday}
                hasContent={(w) =>
                  (days.find((x) => x.weekday === w)?.meals.length ?? 0) > 0
                }
                onCopy={(w) => {
                  edit(duplicateMealDay(days, day.weekday, w));
                  openDays([w]);
                }}
              />
              {pick ? (
                <MealPicker
                  slot={pickerSlot(day, pick.replace)}
                  askSlot={pick.replace === null}
                  onCancel={() => setPicker(null)}
                  onPick={(meal, slot) => {
                    const target = pick.replace
                      ? day.meals.find((m) => m.uid === pick.replace)
                      : undefined;
                    const fresh = draftFromLibraryMeal(
                      meal,
                      target?.slot ?? slot,
                      target?.gramsEdited ? "1" : (target?.portion ?? "1"),
                      target?.id,
                    );
                    edit(
                      days.map((x) =>
                        x.weekday === day.weekday
                          ? {
                              ...x,
                              meals: target
                                ? x.meals.map((m) =>
                                    m.uid === target.uid ? fresh : m,
                                  )
                                : [...x.meals, fresh],
                            }
                          : x,
                      ),
                    );
                    setPicker(null);
                  }}
                />
              ) : (
                <button type="button" className={`${BUTTON} mt-3`} onClick={() => setPicker({ weekday: day.weekday, replace: null })} aria-label={t("plan.meals.addTo", { weekday: t(`plan.weekdayLong.${day.weekday}`) })}>
                  {t("plan.meals.add")}
                </button>
              )}
            </DayRow>
          );
        })}
      </ul>
      <SaveBar dirty={dirty} pending={save.isPending} conflict={conflict} blocked={blocked} failed={generic} invalid={invalid} onSave={onSave} onDiscard={onDiscard} />
    </section>
  );
}
