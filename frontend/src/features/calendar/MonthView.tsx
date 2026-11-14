import { useId } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import { type CalendarDay, useCalendar } from "../../api/calendar";
import { addDays, addMonths, DAY_FORMAT, formatDay, isIsoDate, isMonth, mondayOf, monthGridRange, monthOf } from "../../lib/calendarDates";
import { localDay } from "../../lib/today";
import type { UnitSystem } from "../../lib/units";
import { MonthDayDetail } from "./MonthDayDetail";
import { MonthKpis } from "./MonthKpis";
import { QueryState } from "./QueryState";
import { RangeControls } from "./RangeControls";
import { StatusBadge } from "./StatusBadge";
import { dayBadge } from "./status";

/** One day of the grid: selects the day, and summarises it on hover or keyboard focus (D103). */
function DayCell({ day, inMonth, selected, column, to }: { day: CalendarDay; inMonth: boolean; selected: boolean; column: number; to: string }) {
  const { t, i18n } = useTranslation();
  const tipId = useId();
  const percent = day.nutrition_completion === null ? null : Math.round(day.nutrition_completion * 100);
  const label = formatDay(day.date, i18n.language, DAY_FORMAT.weekdayDayMonthLong);
  const status = t(`calendar.status.${dayBadge(day)}`);
  return (
    <li
      aria-current={day.is_today ? "date" : undefined}
      data-selected={selected || undefined}
      className={`group relative min-h-16 ${selected ? "bg-spruce/15" : inMonth ? "bg-chalk" : "bg-line/50 text-slate"} ${
        selected ? "outline outline-2 -outline-offset-2 outline-spruce" : day.is_today ? "outline outline-2 -outline-offset-2 outline-plate" : ""
      }`}
    >
      <Link
        to={to}
        aria-describedby={tipId}
        className="flex h-full min-h-16 flex-col items-center gap-1 p-1 text-iron no-underline hover:bg-line"
      >
        <span className="sr-only">
          {label}
          {selected && ` (${t("calendar.month.selected")})`}
        </span>
        <span aria-hidden="true" className="text-step--1 font-semibold">
          {Number(day.date.slice(8))}
        </span>
        <StatusBadge kind={dayBadge(day)} compact />
        {percent !== null && <span className="text-step--1 text-slate">{t("calendar.month.nutrition", { percent })}</span>}
      </Link>
      {/* Hover needs a pointer; keyboard users get it on focus, touch users select the day instead. */}
      <div
        id={tipId}
        role="tooltip"
        className={`pointer-events-none absolute top-full z-20 hidden w-48 rounded-md border-2 border-iron bg-chalk p-2 text-left text-step--1 text-iron shadow-lg group-hover:block group-has-[a:focus-visible]:block ${
          column >= 4 ? "right-0" : "left-0"
        }`}
      >
        <p aria-hidden="true" className="font-semibold">
          {label}
        </p>
        <p>{t("calendar.month.tip.training", { name: day.training_day_name ?? t("calendar.restDay"), status })}</p>
        <p>
          {day.planned_meal_count > 0
            ? t("calendar.meals", { eaten: day.eaten_meal_count, planned: day.planned_meal_count })
            : t("calendar.noMeals")}
        </p>
        <p>{t("calendar.month.tip.energy", { eaten: day.energy.eaten.kcal, burned: day.energy.burned.total_kcal })}</p>
      </div>
    </li>
  );
}

/**
 * Month view (spec F9, D103): what the view is for, the month's figures, a Monday-start grid with
 * the training badge and nutrition % per day, and below it everything about the selected day.
 * `monthPath` is the route of this view (`?month=`, with the selected day in `?day=`), `weekPath`
 * the Week view the day detail links to; `dayPath` is the athlete's own page of a day and
 * `readOnly` the coach context.
 */
export function MonthView({
  athleteId,
  timezone,
  units,
  monthPath,
  weekPath,
  dayPath,
  readOnly = false,
}: {
  athleteId: string;
  timezone: string;
  units: UnitSystem;
  monthPath: string;
  weekPath: string;
  dayPath?: (date: string) => string;
  readOnly?: boolean;
}) {
  const { t, i18n } = useTranslation();
  const [params] = useSearchParams();
  const today = localDay(new Date(), timezone, i18n.language).isoDate;
  const requested = params.get("month");
  const month = isMonth(requested) ? requested : monthOf(today);
  const { from, to } = monthGridRange(month);
  const requestedDay = params.get("day");
  const selected = isIsoDate(requestedDay) && requestedDay >= from && requestedDay <= to ? requestedDay : null;
  const calendar = useCalendar(athleteId, from, to);
  const link = (m: string) => `${monthPath}?month=${m}`;
  const title = formatDay(`${month}-01`, i18n.language, DAY_FORMAT.monthYear);
  const weekdayLabels = Array.from({ length: 7 }, (_, i) =>
    formatDay(addDays("2026-10-26", i), i18n.language, DAY_FORMAT.weekdayShort),
  );

  return (
    <>
      <RangeControls
        title={title}
        prevTo={link(addMonths(month, -1))}
        nextTo={link(addMonths(month, 1))}
        currentTo={monthPath}
        prevLabel={t("calendar.month.prev")}
        nextLabel={t("calendar.month.next")}
      />
      <p className="mb-4 text-step--1 text-slate" data-testid="month-description">
        {t(`calendar.month.about.${readOnly ? "coach" : "athlete"}`)}
      </p>
      <QueryState isPending={calendar.isPending} isError={calendar.isError} onRetry={() => void calendar.refetch()} />
      {calendar.data && (
        <>
          <MonthKpis
            days={calendar.data.days.filter((d) => monthOf(d.date) === month)}
            today={today}
            title={t("calendar.month.kpis.title", { month: title })}
          />
          <div aria-hidden="true" className="grid grid-cols-7 gap-px text-center text-step--1 font-semibold text-slate">
            {weekdayLabels.map((label) => (
              <span key={label}>{label}</span>
            ))}
          </div>
          <ol aria-label={t("calendar.month.listLabel")} className="mt-1 grid grid-cols-7 gap-px bg-line">
            {calendar.data.days.map((day, i) => (
              <DayCell
                key={day.date}
                day={day}
                inMonth={monthOf(day.date) === month}
                selected={day.date === selected}
                column={i % 7}
                to={`${link(month)}&day=${day.date}`}
              />
            ))}
          </ol>
          <p className="mt-3 text-step--1 text-slate">{t("calendar.month.legend")}</p>
        </>
      )}
      {selected && (
        <MonthDayDetail
          athleteId={athleteId}
          date={selected}
          units={units}
          timezone={timezone}
          weekTo={`${weekPath}?week=${mondayOf(selected)}`}
          dayTo={dayPath?.(selected)}
        />
      )}
    </>
  );
}
