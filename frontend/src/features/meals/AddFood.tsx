import { useDeferredValue, useId, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type Food,
  type MealSlot,
  type OffProduct,
  useCreateFood,
  useFoodSearch,
  useImportOffFood,
  useLogMeal,
  useOffSearch,
} from "../../api/meals";

const SLOTS: MealSlot[] = ["breakfast", "lunch", "dinner", "snack"];
const INPUT =
  "mt-1 block min-h-12 w-full rounded-md border-2 border-iron/35 bg-white px-3";
const BUTTON =
  "min-h-12 rounded-md border-2 border-iron px-4 font-semibold hover:bg-line disabled:opacity-60";
const PRIMARY =
  "min-h-12 rounded-md bg-spruce px-4 font-semibold text-chalk hover:bg-spruce-dark disabled:opacity-60";

const FORM_FIELDS = [
  { key: "name", label: "meals.add.customName", type: "text" },
  { key: "kcal", label: "meals.add.kcal100", type: "number" },
  { key: "protein", label: "meals.add.protein100", type: "number" },
  { key: "carbs", label: "meals.add.carbs100", type: "number" },
  { key: "fat", label: "meals.add.fat100", type: "number" },
] as const;

type Picked = { id: string; name: string };

function CustomFoodForm({ onCreated }: { onCreated: (food: Picked) => void }) {
  const { t } = useTranslation();
  const create = useCreateFood();
  const [form, setForm] = useState({
    name: "",
    kcal: "",
    protein: "",
    carbs: "",
    fat: "",
  });
  const set =
    (key: keyof typeof form) => (event: React.ChangeEvent<HTMLInputElement>) =>
      setForm({ ...form, [key]: event.target.value });
  const numbers = [form.kcal, form.protein, form.carbs, form.fat].map(Number);
  const valid =
    form.name.trim().length >= 2 &&
    [form.kcal, form.protein, form.carbs, form.fat].every((v) => v !== "") &&
    numbers.every((n) => n >= 0);
  return (
    <form
      className="mt-2 border-l-4 border-plate pl-3"
      onSubmit={(event) => {
        event.preventDefault();
        if (!valid) return;
        create.mutate(
          {
            name: form.name.trim(),
            kcal_per_100g: numbers[0]!,
            protein_g_per_100g: numbers[1]!,
            carbs_g_per_100g: numbers[2]!,
            fat_g_per_100g: numbers[3]!,
            diet_tags: [],
            allergen_tags: [],
          },
          { onSuccess: (food) => onCreated({ id: food.id, name: food.name }) },
        );
      }}
    >
      {FORM_FIELDS.map(({ key, label, type }) => (
        <label key={key} className="mt-2 block">
          <span className="font-semibold">{t(label)}</span>
          <input
            type={type}
            inputMode={type === "number" ? "decimal" : undefined}
            step="any"
            min={type === "number" ? 0 : undefined}
            value={form[key]}
            onChange={set(key)}
            className={INPUT}
          />
        </label>
      ))}
      <button
        type="submit"
        disabled={!valid || create.isPending}
        className={`${PRIMARY} mt-3`}
      >
        {t("meals.add.createFood")}
      </button>
      {create.isError && (
        <p role="alert" className="mt-2 text-alert">
          {t("meals.failed")}
        </p>
      )}
    </form>
  );
}

/** Adds off-plan food (F12): pick from the library, an Open Food Facts product or a new custom food. */
export function AddFood({
  athleteId,
  date,
}: {
  athleteId: string;
  date: string;
}) {
  const { t } = useTranslation();
  const id = useId();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [onlineQuery, setOnlineQuery] = useState("");
  const [custom, setCustom] = useState(false);
  const [picked, setPicked] = useState<Picked | null>(null);
  const [grams, setGrams] = useState("100");
  const [slot, setSlot] = useState<MealSlot>("snack");
  const library = useFoodSearch(useDeferredValue(text));
  const online = useOffSearch(onlineQuery);
  const importFood = useImportOffFood();
  const logMeal = useLogMeal(athleteId);

  const close = () => {
    setOpen(false);
    setText("");
    setOnlineQuery("");
    setCustom(false);
    setPicked(null);
  };

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={`${BUTTON} mt-4`}
      >
        {t("meals.add.open")}
      </button>
    );
  }

  const gramsValid = Number(grams) > 0 && Number(grams) <= 2000;
  const addOnline = (product: OffProduct) =>
    product.imported_food_id
      ? setPicked({ id: product.imported_food_id, name: product.name })
      : importFood.mutate(product.code, {
          onSuccess: (food: Food) =>
            setPicked({ id: food.id, name: food.name }),
        });

  return (
    <section
      aria-label={t("meals.add.open")}
      className="mt-4 border-l-4 border-plate pl-3"
    >
      {picked ? (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (!gramsValid) return;
            logMeal.mutate(
              {
                date,
                planned_meal_id: null,
                status: "extra",
                slot,
                items: [{ food_id: picked.id, grams: Number(grams) }],
              },
              { onSuccess: close },
            );
          }}
        >
          <p className="font-semibold">{picked.name}</p>
          <label className="mt-2 block">
            <span className="font-semibold">{t("meals.add.grams")}</span>
            <input
              type="number"
              inputMode="decimal"
              min={0.1}
              max={2000}
              step="any"
              value={grams}
              onChange={(e) => setGrams(e.target.value)}
              className={INPUT}
            />
          </label>
          <label className="mt-2 block">
            <span className="font-semibold">{t("meals.add.slot")}</span>
            <select
              value={slot}
              onChange={(e) => setSlot(e.target.value as MealSlot)}
              className={INPUT}
            >
              {SLOTS.map((s) => (
                <option key={s} value={s}>
                  {t(`calendar.today.slot.${s}`)}
                </option>
              ))}
            </select>
          </label>
          <div className="mt-3 flex gap-2">
            <button
              type="submit"
              disabled={!gramsValid || logMeal.isPending}
              className={PRIMARY}
            >
              {t("meals.add.submit")}
            </button>
            <button
              type="button"
              onClick={() => setPicked(null)}
              className={BUTTON}
            >
              {t("meals.cancel")}
            </button>
          </div>
          {logMeal.isError && (
            <p role="alert" className="mt-2 text-alert">
              {t("meals.failed")}
            </p>
          )}
        </form>
      ) : (
        <>
          <label htmlFor={id} className="block font-semibold">
            {t("meals.add.search")}
          </label>
          <input
            id={id}
            type="search"
            value={text}
            onChange={(e) => setText(e.target.value)}
            autoComplete="off"
            maxLength={100}
            className={INPUT}
          />
          <ul className="mt-2">
            {(library.data ?? []).map((food) => (
              <li key={food.id}>
                <button
                  type="button"
                  onClick={() => setPicked({ id: food.id, name: food.name })}
                  className="min-h-12 w-full border-b border-line py-2 text-left font-semibold hover:bg-line"
                >
                  {food.name}
                  <span className="text-step--1 font-normal text-slate">
                    {" "}
                    ·{" "}
                    {t("meals.add.per100", {
                      count: Math.round(food.kcal_per_100g),
                    })}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          <div className="mt-2 flex flex-wrap gap-2">
            <button
              type="button"
              disabled={text.trim().length < 2}
              onClick={() => setOnlineQuery(text.trim())}
              className={BUTTON}
            >
              {t("meals.add.searchOnline")}
            </button>
            <button
              type="button"
              onClick={() => setCustom(!custom)}
              aria-expanded={custom}
              className={BUTTON}
            >
              {t("meals.add.custom")}
            </button>
          </div>
          {onlineQuery && online.data && !online.data.available && (
            <p role="status" className="mt-2 text-slate">
              {online.data.message ?? t("meals.add.offUnavailable")}
            </p>
          )}
          {online.isError && (
            <p role="alert" className="mt-2 text-alert">
              {t("meals.add.offUnavailable")}
            </p>
          )}
          {online.data?.available && (
            <ul className="mt-2" aria-label={t("meals.add.onlineResults")}>
              {online.data.items.map((product) => (
                <li key={product.code}>
                  <button
                    type="button"
                    disabled={importFood.isPending}
                    onClick={() => addOnline(product)}
                    className="min-h-12 w-full border-b border-line py-2 text-left font-semibold hover:bg-line"
                  >
                    {product.name}
                    <span className="text-step--1 font-normal text-slate">
                      {" "}
                      ·{" "}
                      {t("meals.add.per100", {
                        count: Math.round(product.kcal_per_100g),
                      })}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {importFood.isError && (
            <p role="alert" className="mt-2 text-alert">
              {t("meals.add.offUnavailable")}
            </p>
          )}
          {custom && <CustomFoodForm onCreated={setPicked} />}
        </>
      )}
      <button
        type="button"
        onClick={close}
        className="mt-2 min-h-12 px-4 font-semibold text-spruce underline underline-offset-4"
      >
        {t("meals.add.close")}
      </button>
    </section>
  );
}
