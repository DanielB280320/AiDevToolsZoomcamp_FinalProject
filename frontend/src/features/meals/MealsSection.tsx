import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { DayView } from "../../api/calendar";
import { useDeleteMealLog, useLogMeal } from "../../api/meals";
import { AddFood } from "./AddFood";

const ADJUSTED = "adjusted" as const;

type DayMeal = DayView["meals"][number];

const BUTTON =
  "min-h-12 rounded-md border-2 border-iron px-4 font-semibold hover:bg-line disabled:opacity-60";
const PRIMARY =
  "min-h-12 rounded-md bg-spruce px-4 font-semibold text-chalk hover:bg-spruce-dark disabled:opacity-60";

/** Grams per planned food, editable (F12 "Adjust"). Saving logs the meal as `adjusted`. */
function AdjustForm({
  meal,
  onSave,
  onCancel,
  busy,
}: {
  meal: DayMeal;
  onSave: (items: { food_id: string; grams: number }[]) => void;
  onCancel: () => void;
  busy: boolean;
}) {
  const { t } = useTranslation();
  const source = meal.log?.items.length
    ? meal.log.items
    : meal.planned_meal.items;
  const [grams, setGrams] = useState(() =>
    source.map((item) => String(item.grams)),
  );
  const valid = grams.every((g) => Number(g) > 0 && Number(g) <= 2000);
  return (
    <form
      className="mt-2 border-l-4 border-plate pl-3"
      onSubmit={(event) => {
        event.preventDefault();
        if (valid)
          onSave(
            source.map((item, i) => ({
              food_id: item.food.id,
              grams: Number(grams[i]),
            })),
          );
      }}
    >
      {source.map((item, i) => (
        <label
          key={item.food.id}
          className="mt-2 flex items-center justify-between gap-3"
        >
          <span>{item.food.name}</span>
          <span className="flex items-center gap-1">
            <input
              type="number"
              inputMode="decimal"
              min={0.1}
              max={2000}
              step="any"
              value={grams[i]}
              aria-label={t("meals.gramsOf", { name: item.food.name })}
              onChange={(event) =>
                setGrams(
                  grams.map((g, j) => (j === i ? event.target.value : g)),
                )
              }
              className="min-h-12 w-24 rounded-md border-2 border-iron/35 bg-white px-3 text-right"
            />
            <span>{t("meals.unitG")}</span>
          </span>
        </label>
      ))}
      <div className="mt-3 flex gap-2">
        <button type="submit" disabled={!valid || busy} className={PRIMARY}>
          {t("meals.saveAdjusted")}
        </button>
        <button type="button" onClick={onCancel} className={BUTTON}>
          {t("meals.cancel")}
        </button>
      </div>
    </form>
  );
}

function MealRow({
  athleteId,
  date,
  meal,
}: {
  athleteId: string;
  date: string;
  meal: DayMeal;
}) {
  const { t } = useTranslation();
  const { planned_meal: planned, log } = meal;
  const logMeal = useLogMeal(athleteId);
  const undo = useDeleteMealLog(athleteId);
  const [adjusting, setAdjusting] = useState(false);
  const busy = logMeal.isPending || undo.isPending;
  const send = (status: "eaten" | "skipped") =>
    logMeal.mutate({ date, planned_meal_id: planned.id, status });

  return (
    <li className="border-b border-line py-3">
      <div className="flex items-baseline justify-between gap-3">
        <span>
          <span className="text-step--1 font-semibold uppercase text-slate">
            {t(`calendar.today.slot.${planned.slot}`)}
          </span>{" "}
          {planned.meal.name}
        </span>
        <span className="text-step--1 text-slate">
          {log && log.status !== "skipped"
            ? t("meals.loggedKcal", { count: log.totals.kcal })
            : t("calendar.today.kcal", { count: planned.totals.kcal })}
        </span>
      </div>
      {log && (
        <p className="mt-1 text-step--1 font-semibold" role="status">
          {t(`meals.status.${log.status as "eaten" | "adjusted" | "skipped"}`)}
        </p>
      )}
      {adjusting ? (
        <AdjustForm
          meal={meal}
          busy={busy}
          onCancel={() => setAdjusting(false)}
          onSave={(items) =>
            logMeal.mutate(
              { date, planned_meal_id: planned.id, status: ADJUSTED, items },
              { onSuccess: () => setAdjusting(false) },
            )
          }
        />
      ) : (
        <div className="mt-2 flex flex-wrap gap-2">
          {!log && (
            <button
              type="button"
              disabled={busy}
              onClick={() => send("eaten")}
              aria-label={t("meals.eatenAsPlannedFor", {
                name: planned.meal.name,
              })}
              className={PRIMARY}
            >
              {t("meals.eatenAsPlanned")}
            </button>
          )}
          <button
            type="button"
            disabled={busy}
            onClick={() => setAdjusting(true)}
            aria-label={t("meals.adjustFor", { name: planned.meal.name })}
            className={BUTTON}
          >
            {t("meals.adjust")}
          </button>
          {log?.status !== "skipped" && (
            <button
              type="button"
              disabled={busy}
              onClick={() => send("skipped")}
              aria-label={t("meals.skipFor", { name: planned.meal.name })}
              className={BUTTON}
            >
              {t("meals.skip")}
            </button>
          )}
          {log && (
            <button
              type="button"
              disabled={busy}
              onClick={() => undo.mutate(log.id)}
              aria-label={t("meals.undoFor", { name: planned.meal.name })}
              className={BUTTON}
            >
              {t("meals.undo")}
            </button>
          )}
        </div>
      )}
      {(logMeal.isError || undo.isError) && (
        <p role="alert" className="mt-2 text-alert">
          {t("meals.failed")}
        </p>
      )}
    </li>
  );
}

function ExtraRow({
  athleteId,
  log,
}: {
  athleteId: string;
  log: DayView["extra_meal_logs"][number];
}) {
  const { t } = useTranslation();
  const undo = useDeleteMealLog(athleteId);
  return (
    <li className="flex items-center justify-between gap-3 border-b border-line py-2">
      <span>
        {log.items
          .map((item) => `${item.food.name} ${item.grams} g`)
          .join(", ")}
        <span className="text-step--1 text-slate">
          {" "}
          · {t("calendar.today.kcal", { count: log.totals.kcal })}
        </span>
      </span>
      <button
        type="button"
        disabled={undo.isPending}
        onClick={() => undo.mutate(log.id)}
        aria-label={t("meals.removeFor", {
          name: log.items.map((i) => i.food.name).join(", "),
        })}
        className={BUTTON}
      >
        {t("meals.remove")}
      </button>
    </li>
  );
}

/** Today's meals (F12): one tap to check off as planned, adjust grams, skip, and add off-plan food. */
export function MealsSection({
  athleteId,
  day,
}: {
  athleteId: string;
  day: DayView;
}) {
  const { t } = useTranslation();
  return (
    <>
      {day.meals.length === 0 ? (
        <p className="mt-2 text-slate">{t("calendar.noMeals")}</p>
      ) : (
        <ul className="mt-2">
          {day.meals.map((meal) => (
            <MealRow
              key={meal.planned_meal.id}
              athleteId={athleteId}
              date={day.date}
              meal={meal}
            />
          ))}
        </ul>
      )}
      {day.extra_meal_logs.length > 0 && (
        <>
          <h3 className="mt-4 font-semibold">{t("meals.extraTitle")}</h3>
          <ul>
            {day.extra_meal_logs.map((log) => (
              <ExtraRow key={log.id} athleteId={athleteId} log={log} />
            ))}
          </ul>
        </>
      )}
      <AddFood athleteId={athleteId} date={day.date} />
    </>
  );
}
