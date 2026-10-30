import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router";

import { type CalendarDay, useCalendar } from "../api/calendar";
import { useSignedInUser } from "../components/RequireAuth";
import { CalendarNav } from "../features/calendar/CalendarNav";
import { EnergySummary } from "../features/calendar/EnergySummary";
import { MoveSession } from "../features/calendar/MoveSession";
import { QueryState } from "../features/calendar/QueryState";
import { RangeControls } from "../features/calendar/RangeControls";
import { StatusBadge } from "../features/calendar/StatusBadge";
import { dayBadge } from "../features/calendar/status";
import { addDays, DAY_FORMAT, formatDay, isIsoDate, mondayOf } from "../lib/calendarDates";
import { localDay } from "../lib/today";
import { paths } from "../paths";

function DayRow({
  day,
  athleteId,
  targets,
}: {
  day: CalendarDay;
  athleteId: string;
  targets: string[];
}) {
  const { t, i18n } = useTranslation();
  const movable = day.training_status === "planned" && targets.length > 0;
  const weekday = formatDay(day.date, i18n.language, DAY_FORMAT.weekday);
  const date = formatDay(day.date, i18n.language, DAY_FORMAT.dayMonth);
  return (
    <li
      aria-current={day.is_today ? "date" : undefined}
      className={`border-b border-line py-3 ${day.is_today ? "border-l-4 border-l-plate pl-3" : ""}`}
    >
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="font-display text-step-1 font-bold leading-tight">
            {weekday} <span className="font-semibold text-slate">{date}</span>
            {day.is_today && <span className="ml-2 text-step--1 text-spruce">{t("calendar.todayMarker")}</span>}
          </p>
          <p className="text-step-0">
            {day.training_day_name ?? t("calendar.restDay")}
            {day.moved && <span className="ml-2 text-step--1 text-slate">{t("calendar.moved")}</span>}
          </p>
        </div>
        <StatusBadge kind={dayBadge(day)} />
      </div>
      <p className="mt-1 text-step--1 text-slate">
        {day.planned_meal_count > 0
          ? t("calendar.meals", { eaten: day.eaten_meal_count, planned: day.planned_meal_count })
          : t("calendar.noMeals")}
      </p>
      <EnergySummary energy={day.energy} compact />
      {movable && (
        <div className="mt-2">
          <MoveSession athleteId={athleteId} day={day} targets={targets} />
        </div>
      )}
    </li>
  );
}

/** Week view (spec F9): Monday to Sunday with the training status of each day and a move control. */
export function WeekPage() {
  const { t, i18n } = useTranslation();
  const me = useSignedInUser();
  const [params] = useSearchParams();
  const today = localDay(new Date(), me.timezone, i18n.language).isoDate;
  const requested = params.get("week");
  const monday = mondayOf(isIsoDate(requested) ? requested : today);
  const sunday = addDays(monday, 6);
  const calendar = useCalendar(me.id, monday, sunday);

  const days = calendar.data?.days ?? [];
  // Free days the athlete could move a session to: no session there, today or later.
  const targetsFor = (day: CalendarDay) =>
    days.filter((d) => d.training_status === "rest" && d.date >= today && d.date !== day.date).map((d) => d.date);
  const link = (monday: string) => `${paths.week}?week=${monday}`;

  return (
    <div className="max-w-[40rem]">
      <CalendarNav />
      <RangeControls
        title={t("calendar.week.title", {
          from: formatDay(monday, i18n.language, DAY_FORMAT.dayMonth),
          to: formatDay(sunday, i18n.language, DAY_FORMAT.dayMonth),
        })}
        prevTo={link(addDays(monday, -7))}
        nextTo={link(addDays(monday, 7))}
        currentTo={paths.week}
        prevLabel={t("calendar.week.prev")}
        nextLabel={t("calendar.week.next")}
      />
      <QueryState
        isPending={calendar.isPending}
        isError={calendar.isError}
        onRetry={() => void calendar.refetch()}
      />
      {calendar.data && (
        <ol aria-label={t("calendar.week.listLabel")} className="border-t-4 border-iron">
          {days.map((day) => (
            <DayRow key={day.date} day={day} athleteId={me.id} targets={targetsFor(day)} />
          ))}
        </ol>
      )}
    </div>
  );
}
