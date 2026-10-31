import { useTranslation } from "react-i18next";
import { Link, Navigate } from "react-router";

import { useSignedInUser } from "../components/RequireAuth";
import { CalendarNav } from "../features/calendar/CalendarNav";
import { TodayView } from "../features/calendar/TodayView";
import { localDay } from "../lib/today";
import { paths } from "../paths";

/**
 * Home screen (spec F9). Athletes see their day (#28); the coach
 * dashboard (#48) replaces the coach placeholder later. "Today" is the user's day in `Me.timezone`.
 */
export function TodayPage() {
  const { t, i18n } = useTranslation();
  const me = useSignedInUser();
  // F2.2: a new athlete sets up the plan before seeing Today.
  if (me.role === "athlete" && !me.onboarding_completed) return <Navigate to={paths.onboarding} replace />;
  const today = localDay(new Date(), me.timezone, i18n.language);

  return (
    <article className="max-w-[40rem]">
      {me.role === "athlete" && <CalendarNav />}
      <p className="text-step-1 text-slate">{t("today.greeting", { name: me.display_name })}</p>
      <h1 className="mt-2 font-display font-bold">
        <time dateTime={today.isoDate} className="block">
          <span className="block text-step-5 leading-none sm:text-[4.768rem]">{today.weekday}</span>{" "}
          <span className="mt-1 block text-step-3 font-semibold leading-tight text-slate sm:text-step-4">
            {today.date}
          </span>
        </time>
      </h1>
      {me.role === "coach" ? (
        <div className="mt-8 max-w-[52ch] border-t-4 border-iron pt-4 text-step-0">
          <p>{t("today.placeholder.coach")}</p>
          <p className="mt-3">
            <Link to={paths.coach} className="font-semibold">
              {t("coach.title")}
            </Link>
          </p>
        </div>
      ) : (
        <TodayView me={me} />
      )}
    </article>
  );
}
