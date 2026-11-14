import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { type DayView, useDay } from "../../api/calendar";
import { CheckCircleIcon, DumbbellIcon, FlameIcon, NoteIcon, UtensilsIcon } from "../../components/icons";
import { PrBadge } from "../../components/PrBadge";
import { DAY_FORMAT, formatDay } from "../../lib/calendarDates";
import type { UnitSystem } from "../../lib/units";
import { SessionChartView } from "../charts/SessionChartView";
import { NoteThread } from "../notes/NoteThread";
import { DecidedSuggestions } from "../suggestions/DecidedSuggestions";
import { EnergySummary } from "./EnergySummary";
import { QueryState } from "./QueryState";
import { StatusBadge } from "./StatusBadge";
import { badgeKind, statusReason } from "./status";
import { CompletionRing, toPercent } from "./TodayView";

const ICON = "size-6 text-spruce";
const LINK = "inline-flex min-h-11 items-center font-semibold text-spruce underline underline-offset-4";

function Part({ id, title, icon, children }: { id: string; title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <section aria-labelledby={id} className="mt-6">
      <h3 id={id} className="flex items-center gap-2 font-display text-step-1 font-bold">
        {icon}
        {title}
      </h3>
      {children}
    </section>
  );
}

/** What was logged for each planned meal, then the meals logged outside the plan. */
function MealsLogged({ day }: { day: DayView }) {
  const { t } = useTranslation();
  if (day.meals.length === 0 && day.extra_meal_logs.length === 0) return <p className="mt-1 text-slate">{t("calendar.noMeals")}</p>;
  const row = "flex flex-wrap items-baseline justify-between gap-x-3 border-b border-line py-2";
  const kcal = (value: number) => t("calendar.month.day.kcal", { value: Math.round(value) });
  return (
    <ul className="mt-1" data-testid="month-day-meals">
      {day.meals.map(({ planned_meal: planned, log }) => (
        <li key={planned.id} className={row}>
          <span className="min-w-0 break-words">
            <span className="text-step--1 font-semibold uppercase text-slate">{t(`calendar.today.slot.${planned.slot}`)}</span>{" "}
            {planned.meal.name}
          </span>
          <span className="text-step--1 text-slate">
            {log ? t(`meals.status.${log.status as "eaten" | "adjusted" | "skipped"}`) : t("calendar.today.notLogged")}
            {log && log.status !== "skipped" && ` · ${kcal(log.totals.kcal)}`}
          </span>
        </li>
      ))}
      {day.extra_meal_logs.map((log) => (
        <li key={log.id} className={row}>
          <span className="min-w-0 break-words">
            <span className="text-step--1 font-semibold uppercase text-slate">
              {log.slot ? t(`calendar.today.slot.${log.slot}`) : t("calendar.month.day.extraMeal")}
            </span>{" "}
            {log.items.map((item) => item.food.name).join(", ")}
          </span>
          <span className="text-step--1 text-slate">
            {t("calendar.month.day.extraLogged")} · {kcal(log.totals.kcal)}
          </span>
        </li>
      ))}
    </ul>
  );
}

/**
 * Everything about the day selected in the Month view (D103): its training status with the reason,
 * the session chart (planned vs. done per set) once the workout was started, the meals logged, the
 * estimated energy balance, the suggestions decided that day and the coach notes. Read-only for
 * both readers; `dayTo` leads the athlete to the day's own page, where sets and meals are logged.
 */
export function MonthDayDetail({
  athleteId,
  date,
  units,
  timezone,
  weekTo,
  dayTo,
}: {
  athleteId: string;
  date: string;
  units: UnitSystem;
  timezone: string;
  /** The Week view of the day's week. */
  weekTo: string;
  /** The day's own page; left out for the coach, who has none. */
  dayTo?: string;
}) {
  const { t, i18n } = useTranslation();
  const day = useDay(athleteId, date);
  const ref = useRef<HTMLElement>(null);
  // The detail sits below the grid: bring it into view when a day is picked (no-op in jsdom).
  useEffect(() => {
    ref.current?.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
  }, [date]);

  const session = day.data?.session ?? null;
  const reason = day.data ? statusReason(day.data.training_status, day.data.training_completion) : null;
  const records = session?.exercises.filter((e) => e.is_pr) ?? [];
  return (
    <section ref={ref} aria-labelledby="month-day" className="mt-6 scroll-mt-4 border-t-4 border-iron pt-3" data-testid="month-day-detail">
      <h2 id="month-day" className="font-display text-step-2 font-bold">
        {formatDay(date, i18n.language, DAY_FORMAT.weekdayDayMonthLong)}
      </h2>
      <p className="flex flex-wrap gap-x-4">
        {dayTo && (
          <Link to={dayTo} className={LINK}>
            {t("calendar.month.day.open")}
          </Link>
        )}
        <Link to={weekTo} className={LINK}>
          {t("calendar.month.day.week")}
        </Link>
      </p>
      {!day.data && <QueryState isPending={day.isPending} isError={day.isError} onRetry={() => void day.refetch()} />}
      {day.data && reason && (
        <>
          <Part id="month-day-training" title={t("calendar.today.training")} icon={<DumbbellIcon className={ICON} />}>
            <p className="mt-1 flex items-center gap-3">
              <StatusBadge kind={badgeKind(day.data.training_status, day.data.training_completion)} />
              <span className="font-semibold">{session?.training_day_name ?? t("calendar.restDay")}</span>
            </p>
            <p className="mt-1 text-step--1 text-slate" data-testid="status-reason">
              {reason.key === "partialFinished" ? t("calendar.week.reason.partialFinished", { value: reason.value }) : t(`calendar.week.reason.${reason.key}`)}
            </p>
            {session?.status === "done" && session.completion != null && <CompletionRing percent={toPercent(session.completion)} />}
            {records.length > 0 && (
              <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1" aria-label={t("calendar.month.day.records")}>
                {records.map((e) => (
                  <li key={e.exercise.id} className="font-semibold">
                    {e.exercise.name} <PrBadge />
                  </li>
                ))}
              </ul>
            )}
            {session && session.status !== "planned" && (
              <div className="min-w-0">
                <SessionChartView athleteId={athleteId} sessionId={session.id} units={units} />
              </div>
            )}
            {session?.status === "planned" && (
              <ul className="mt-2">
                {session.exercises.map((e) => (
                  <li key={e.planned_exercise_id ?? e.order} className="flex justify-between gap-3 border-b border-line py-2">
                    <span className="font-semibold">{e.exercise.name}</span>
                    <span className="text-step--1 text-slate">{t("calendar.today.sets", { count: e.sets.length })}</span>
                  </li>
                ))}
              </ul>
            )}
          </Part>

          <Part id="month-day-meals" title={t("calendar.today.meals")} icon={<UtensilsIcon className={ICON} />}>
            <MealsLogged day={day.data} />
          </Part>

          <Part id="month-day-energy" title={t("calendar.month.day.energy")} icon={<FlameIcon className={ICON} />}>
            <EnergySummary energy={day.data.energy} compact={false} />
          </Part>

          <DecidedSuggestions athleteId={athleteId} timezone={timezone} day={date} className="mt-6" icon={<CheckCircleIcon className={ICON} />} />

          {day.data.notes.length > 0 && (
            <Part id="month-day-notes" title={t("calendar.month.day.notes")} icon={<NoteIcon className={ICON} />}>
              <NoteThread athleteId={athleteId} notes={day.data.notes} label={t("notes.dayLabel")} />
            </Part>
          )}
        </>
      )}
    </section>
  );
}
