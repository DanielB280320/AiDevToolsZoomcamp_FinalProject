import { useDeferredValue, useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { isApiError } from "../../api/errors";
import { useFoodSearch, type MealSlot } from "../../api/meals";
import { type Meal, useCreateMeal, useMealSearch } from "../../api/plan";
import { CustomFoodForm } from "../meals/AddFood";
import { BUTTON, PRIMARY, SelectInput, TextInput } from "./fields";

export const SLOTS: MealSlot[] = ["breakfast", "lunch", "dinner", "snack"];

interface PickedFood {
  id: string;
  name: string;
  grams: string;
}

/** Create a custom meal from foods and grams (F8, F6); a new food can be made on the way. */
function CreateMealForm({ slot, onCreated }: { slot: MealSlot; onCreated: (meal: Meal) => void }) {
  const { t } = useTranslation();
  const uid = useId();
  const create = useCreateMeal();
  const [name, setName] = useState("");
  const [slots, setSlots] = useState<MealSlot[]>([slot]);
  const [text, setText] = useState("");
  const [foods, setFoods] = useState<PickedFood[]>([]);
  const [newFood, setNewFood] = useState(false);
  const search = useFoodSearch(useDeferredValue(text));
  const grams = foods.map((f) => Number(f.grams));
  const valid =
    name.trim().length >= 2 && slots.length > 0 && foods.length > 0 && grams.every((g) => g > 0 && g <= 2000);
  const add = (food: { id: string; name: string }) => {
    if (!foods.some((f) => f.id === food.id)) setFoods([...foods, { ...food, grams: "100" }]);
    setText("");
    setNewFood(false);
  };

  return (
    <form
      aria-label={t("plan.meals.create.title")}
      className="mt-3 border-l-4 border-iron pl-3"
      onSubmit={(event) => {
        event.preventDefault();
        if (!valid) return;
        create.mutate(
          { name: name.trim(), slots, items: foods.map((f) => ({ food_id: f.id, grams: Number(f.grams) })) },
          { onSuccess: onCreated },
        );
      }}
    >
      <h5 className="font-display text-step-1 font-bold">{t("plan.meals.create.title")}</h5>
      <TextInput id={`${uid}-name`} label={t("plan.meals.create.name")} value={name} maxLength={120} onChange={setName} />
      <fieldset className="mt-2">
        <legend className="font-semibold">{t("plan.meals.create.slots")}</legend>
        <div className="flex flex-wrap gap-x-4">
          {SLOTS.map((s) => (
            <label key={s} className="flex min-h-12 items-center gap-2">
              <input
                type="checkbox"
                className="size-6"
                checked={slots.includes(s)}
                onChange={(event) => setSlots(event.target.checked ? [...slots, s] : slots.filter((x) => x !== s))}
              />
              {t(`plan.slot.${s}`)}
            </label>
          ))}
        </div>
      </fieldset>
      <ul className="mt-2 flex flex-col gap-2">
        {foods.map((food) => (
          <li key={food.id} className="grid grid-cols-[1fr_6rem_auto] items-end gap-2">
            <span className="break-words font-semibold">{food.name}</span>
            <TextInput
              id={`${uid}-g-${food.id}`}
              label={t("plan.meals.create.gramsOf", { name: food.name })}
              value={food.grams}
              inputMode="decimal"
              onChange={(g) => setFoods(foods.map((f) => (f.id === food.id ? { ...f, grams: g } : f)))}
            />
            <button type="button" className={BUTTON} onClick={() => setFoods(foods.filter((f) => f.id !== food.id))} aria-label={t("plan.meals.create.removeFood", { name: food.name })}>
              <span aria-hidden="true">×</span>
            </button>
          </li>
        ))}
      </ul>
      <TextInput id={`${uid}-food`} label={t("plan.meals.create.searchFood")} value={text} onChange={setText} />
      {search.data && search.data.length > 0 && (
        <ul className="mt-1 flex flex-col gap-2">
          {search.data.map((food) => (
            <li key={food.id}>
              <button type="button" className={`${BUTTON} w-full text-left`} onClick={() => add(food)} aria-label={t("plan.meals.create.addFood", { name: food.name })}>
                {food.name}
              </button>
            </li>
          ))}
        </ul>
      )}
      <button type="button" className={`${BUTTON} mt-2`} onClick={() => setNewFood(!newFood)}>
        {t("plan.meals.create.newFood")}
      </button>
      {newFood && <CustomFoodForm onCreated={add} />}
      <button type="submit" disabled={!valid || create.isPending} className={`${PRIMARY} mt-3`}>
        {t("plan.meals.create.submit")}
      </button>
      {create.isError && (
        <p role="alert" className="mt-2 font-semibold text-alert">
          {isApiError(create.error) && create.error.problem.detail ? create.error.problem.detail : t("plan.meals.create.failed")}
        </p>
      )}
    </form>
  );
}

/** Library search for adding or replacing a meal; the slot filter narrows the list. */
export function MealPicker({
  slot: initialSlot,
  askSlot,
  onPick,
  onCancel,
}: {
  slot: MealSlot;
  /** Adding a meal also picks its slot; replacing keeps the existing slot. */
  askSlot: boolean;
  onPick: (meal: Meal, slot: MealSlot) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const uid = useId();
  const [slot, setSlot] = useState<MealSlot>(initialSlot);
  const [text, setText] = useState("");
  const [creating, setCreating] = useState(false);
  const search = useMealSearch(useDeferredValue(text), slot);

  return (
    <section aria-label={t("plan.meals.picker.title")} className="mt-3 border-2 border-iron/30 p-3">
      {askSlot && (
        <SelectInput id={`${uid}-slot`} label={t("plan.meals.slot")} value={slot} onChange={(v) => setSlot(v as MealSlot)} options={SLOTS.map((s) => ({ value: s, label: t(`plan.slot.${s}`) }))} />
      )}
      <TextInput id={`${uid}-q`} label={t("plan.meals.picker.search")} value={text} onChange={setText} />
      {search.isSuccess && search.data.length === 0 && <p className="mt-1 text-step--1 text-slate">{t("plan.noResults")}</p>}
      {search.isError && <p role="alert" className="mt-1 text-step--1 font-semibold text-alert">{t("plan.meals.picker.failed")}</p>}
      <ul className="mt-2 flex flex-col gap-2">
        {(search.data ?? []).map((meal) => (
          <li key={meal.id}>
            <button type="button" className={`${BUTTON} w-full text-left`} onClick={() => onPick(meal, slot)} aria-label={t("plan.meals.picker.choose", { name: meal.name })}>
              {meal.name}
              <span className="block text-step--1 font-normal text-slate">{t("plan.meals.kcal", { kcal: meal.totals.kcal })}</span>
            </button>
          </li>
        ))}
      </ul>
      <div className="mt-3 flex flex-wrap gap-3">
        <button type="button" className={BUTTON} onClick={() => setCreating(!creating)}>
          {t("plan.meals.create.open")}
        </button>
        <button type="button" className={BUTTON} onClick={onCancel}>
          {t("plan.cancel")}
        </button>
      </div>
      {creating && <CreateMealForm slot={slot} onCreated={(meal) => onPick(meal, slot)} />}
    </section>
  );
}
