import { useTranslation } from "react-i18next";

import type { Plan } from "../../api/plan";
import { ClipboardIcon } from "../../components/icons";
import { localDay } from "../../lib/today";

export type Viewer = "athlete" | "coach";

const DAY_MS = 86_400_000;
const utcDay = (iso: string): number => Date.parse(`${iso}T00:00:00Z`);

/** Week of the plan (1 on the start date), counted in the athlete's time zone (D105). */
export function planWeek(startDate: string, today: string): number {
  return Math.max(
    1,
    Math.floor((utcDay(today) - utcDay(startDate)) / (7 * DAY_MS)) + 1,
  );
}

/** What the active plan is: name, start date, version and a few figures to review (F8, D105). */
export function PlanSummary({
  plan,
  timezone,
  viewer,
}: {
  plan: Plan;
  timezone: string;
  viewer: Viewer;
}) {
  const { t, i18n } = useTranslation();
  const today = localDay(new Date(), timezone, i18n.language).isoDate;
  const mealCount = plan.meal_days.reduce(
    (sum, day) => sum + day.meals.length,
    0,
  );
  const mealDays = plan.meal_days.filter((day) => day.meals.length > 0).length;
  const changed = new Intl.DateTimeFormat(i18n.language, {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: timezone,
  }).format(new Date(plan.updated_at));
  const started = plan.start_date
    ? t("plan.current.startDateValue", {
        date: new Intl.DateTimeFormat(i18n.language, {
          dateStyle: "medium",
          timeZone: "UTC",
        }).format(new Date(utcDay(plan.start_date))),
        week: planWeek(plan.start_date, today),
      })
    : null;
  return (
    <section
      aria-labelledby="plan-current-title"
      className="mt-4 border-2 border-iron/30 p-3"
      data-testid="plan-summary"
    >
      <h2
        id="plan-current-title"
        className="flex items-center gap-2 font-display text-step-2 font-bold"
      >
        <ClipboardIcon className="size-6 text-spruce" />
        {t("plan.current.title")}
      </h2>
      <p className="mt-1 break-words font-display text-step-1 font-bold">
        {plan.name ?? t("plan.current.fallbackName", { version: plan.version })}
      </p>
      <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-step--1">
        {started && (
          <>
            <dt className="font-semibold">{t("plan.current.startDate")}</dt>
            <dd>{started}</dd>
          </>
        )}
        <dt className="font-semibold">{t("plan.current.version")}</dt>
        <dd>
          {t("plan.current.versionValue", {
            version: plan.version,
            source: t(`plan.history.sources.${plan.source}`),
          })}
        </dd>
        <dt className="font-semibold">{t("plan.current.lastChange")}</dt>
        <dd>{changed}</dd>
        <dt className="font-semibold">{t("plan.current.trainingDays")}</dt>
        <dd>{plan.training_days.length}</dd>
        <dt className="font-semibold">{t("plan.current.meals")}</dt>
        <dd>
          {t("plan.current.mealsValue", { count: mealCount, days: mealDays })}
        </dd>
      </dl>
      <p className="mt-2 text-step--1 text-slate">
        {t(`plan.current.review.${viewer}`)}
      </p>
    </section>
  );
}
