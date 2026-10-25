import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import { useCalendar } from "../api/calendar";
import { useSignedInUser } from "../components/RequireAuth";
import { CalendarNav } from "../features/calendar/CalendarNav";
import { QueryState } from "../features/calendar/QueryState";
import { RangeControls } from "../features/calendar/RangeControls";
import { StatusBadge } from "../features/calendar/StatusBadge";
import { dayBadge } from "../features/calendar/status";
import { addDays, addMonths, DAY_FORMAT, formatDay, isMonth, mondayOf, monthGridRange, monthOf } from "../lib/calendarDates";
import { localDay } from "../lib/today";
import { paths } from "../paths";

/** Month view (spec F9): a Monday-start grid with the training badge and nutrition % per day. */
export function MonthPage() {
  const { t, i18n } = useTranslation();
  const me = useSignedInUser();
  const [params] = useSearchParams();
  const today = localDay(new Date(), me.timezone, i18n.language).isoDate;
  const requested = params.get("month");
  const month = isMonth(requested) ? requested : monthOf(today);
  const { from, to } = monthGridRange(month);
  const calendar = useCalendar(me.id, from, to);
  const link = (m: string) => `${paths.month}?month=${m}`;
  const weekdayLabels = Array.from({ length: 7 }, (_, i) =>
    formatDay(addDays("2026-10-26", i), i18n.language, DAY_FORMAT.weekdayShort),
  );

  return (
    <div className="max-w-[40rem]">
      <CalendarNav />
      <RangeControls
        title={formatDay(`${month}-01`, i18n.language, DAY_FORMAT.monthYear)}
        prevTo={link(addMonths(month, -1))}
        nextTo={link(addMonths(month, 1))}
        currentTo={paths.month}
        prevLabel={t("calendar.month.prev")}
        nextLabel={t("calendar.month.next")}
      />
      <QueryState
        isPending={calendar.isPending}
        isError={calendar.isError}
        onRetry={() => void calendar.refetch()}
      />
      {calendar.data && (
        <>
          <div aria-hidden="true" className="grid grid-cols-7 gap-px text-center text-step--1 font-semibold text-slate">
            {weekdayLabels.map((label) => (
              <span key={label}>{label}</span>
            ))}
          </div>
          <ol aria-label={t("calendar.month.listLabel")} className="mt-1 grid grid-cols-7 gap-px bg-line">
            {calendar.data.days.map((day) => {
              const inMonth = monthOf(day.date) === month;
              const percent =
                day.nutrition_completion === null ? null : Math.round(day.nutrition_completion * 100);
              const label = formatDay(day.date, i18n.language, DAY_FORMAT.weekdayDayMonthLong);
              return (
                <li
                  key={day.date}
                  aria-current={day.is_today ? "date" : undefined}
                  className={`min-h-16 ${inMonth ? "bg-chalk" : "bg-line/50 text-slate"} ${
                    day.is_today ? "outline outline-2 -outline-offset-2 outline-plate" : ""
                  }`}
                >
                  <Link
                    to={`${paths.week}?week=${mondayOf(day.date)}`}
                    className="flex h-full min-h-16 flex-col items-center gap-1 p-1 text-iron no-underline hover:bg-line"
                  >
                    <span className="sr-only">{label}</span>
                    <span aria-hidden="true" className="text-step--1 font-semibold">
                      {Number(day.date.slice(8))}
                    </span>
                    <StatusBadge kind={dayBadge(day)} compact />
                    {percent !== null && (
                      <span className="text-step--1 text-slate">{t("calendar.month.nutrition", { percent })}</span>
                    )}
                  </Link>
                </li>
              );
            })}
          </ol>
          <p className="mt-3 text-step--1 text-slate">{t("calendar.month.legend")}</p>
        </>
      )}
    </div>
  );
}
