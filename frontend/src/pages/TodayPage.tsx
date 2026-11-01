import { useTranslation } from "react-i18next";
import { Navigate } from "react-router";

import { useSignedInUser } from "../components/RequireAuth";
import { CalendarNav } from "../features/calendar/CalendarNav";
import { TodayView } from "../features/calendar/TodayView";
import { localDay } from "../lib/today";
import { paths } from "../paths";

/**
 * Home screen (spec F9). Athletes see their day (#28); a coach has no day of their own and lands
 * on the client list (#48). "Today" is the user's day in `Me.timezone`.
 */
export function TodayPage() {
  const { t, i18n } = useTranslation();
  const me = useSignedInUser();
  // F2.2: a new athlete sets up the plan before seeing Today.
  if (me.role === "athlete" && !me.onboarding_completed) return <Navigate to={paths.onboarding} replace />;
  if (me.role === "coach") return <Navigate to={paths.coachClients} replace />;
  const today = localDay(new Date(), me.timezone, i18n.language);

  return (
    <article className="max-w-[40rem]">
      <CalendarNav />
      <p className="text-step-1 text-slate">{t("today.greeting", { name: me.display_name })}</p>
      <h1 className="mt-2 font-display font-bold">
        <time dateTime={today.isoDate} className="block">
          <span className="block text-step-5 leading-none sm:text-[4.768rem]">{today.weekday}</span>{" "}
          <span className="mt-1 block text-step-3 font-semibold leading-tight text-slate sm:text-step-4">
            {today.date}
          </span>
        </time>
      </h1>
      <TodayView me={me} />
    </article>
  );
}
