import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import { type CalendarDay, useCalendar } from "../../api/calendar";
import { addDays, DAY_FORMAT, formatDay, isIsoDate, mondayOf } from "../../lib/calendarDates";
import { localDay } from "../../lib/today";
import { EnergySummary } from "./EnergySummary";
import { MoveSession } from "./MoveSession";
import { QueryState } from "./QueryState";
import { RangeControls } from "./RangeControls";
import { StatusBadge } from "./StatusBadge";
import { dayBadge } from "./status";

function DayRow({
  day,
  athleteId,
  targets,
  readOnly,
  sessionLink,
}: {
  day: CalendarDay;
  athleteId: string;
  targets: string[];
  readOnly: boolean;
  sessionLink?: ((sessionId: string) => string) | undefined;
}) {
  const { t, i18n } = useTranslation();
  const movable = !readOnly && day.training_status === "planned" && targets.length > 0;
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
      {sessionLink && day.session_id && (day.training_status === "done" || day.training_status === "in_progress") && (
        <Link
          to={sessionLink(day.session_id)}
          className="mt-1 inline-flex min-h-11 items-center font-semibold text-spruce underline underline-offset-4"
        >
          {t("coach.client.sessionDetail")}
        </Link>
      )}
      {movable && (
        <div className="mt-2">
          <MoveSession athleteId={athleteId} day={day} targets={targets} />
        </div>
      )}
    </li>
  );
}

/**
 * Week view (spec F9): Monday to Sunday with the training status of each day and a move control.
 * `basePath` is the route of the view (the week is `?week=`); `readOnly` hides the move control
 * (coach context).
 */
export function WeekView({
  athleteId,
  timezone,
  basePath,
  readOnly = false,
  sessionLink,
}: {
  athleteId: string;
  timezone: string;
  basePath: string;
  readOnly?: boolean;
  sessionLink?: (sessionId: string) => string;
}) {
  const { t, i18n } = useTranslation();
  const [params] = useSearchParams();
  const today = localDay(new Date(), timezone, i18n.language).isoDate;
  const requested = params.get("week");
  const monday = mondayOf(isIsoDate(requested) ? requested : today);
  const sunday = addDays(monday, 6);
  const calendar = useCalendar(athleteId, monday, sunday);

  const days = calendar.data?.days ?? [];
  // Free days the athlete could move a session to: no session there, today or later.
  const targetsFor = (day: CalendarDay) =>
    days.filter((d) => d.training_status === "rest" && d.date >= today && d.date !== day.date).map((d) => d.date);
  const link = (monday: string) => `${basePath}?week=${monday}`;

  return (
    <>
      <RangeControls
        title={t("calendar.week.title", {
          from: formatDay(monday, i18n.language, DAY_FORMAT.dayMonth),
          to: formatDay(sunday, i18n.language, DAY_FORMAT.dayMonth),
        })}
        prevTo={link(addDays(monday, -7))}
        nextTo={link(addDays(monday, 7))}
        currentTo={basePath}
        prevLabel={t("calendar.week.prev")}
        nextLabel={t("calendar.week.next")}
      />
      <QueryState isPending={calendar.isPending} isError={calendar.isError} onRetry={() => void calendar.refetch()} />
      {calendar.data && (
        <ol aria-label={t("calendar.week.listLabel")} className="border-t-4 border-iron">
          {days.map((day) => (
            <DayRow
              key={day.date}
              day={day}
              athleteId={athleteId}
              targets={targetsFor(day)}
              readOnly={readOnly}
              sessionLink={sessionLink}
            />
          ))}
        </ol>
      )}
    </>
  );
}
