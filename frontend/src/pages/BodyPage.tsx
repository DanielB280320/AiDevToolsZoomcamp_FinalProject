import { useTranslation } from "react-i18next";
import { Navigate } from "react-router";

import { useSignedInUser } from "../components/RequireAuth";
import { CalendarNav } from "../features/calendar/CalendarNav";
import { BodyTracking } from "../features/body/BodyTracking";
import { localDay } from "../lib/today";
import { paths } from "../paths";

/** Body tracking (spec F14): weigh-ins and the recalculation prompt. "Today" is the user's day. */
export function BodyPage() {
  const { t, i18n } = useTranslation();
  const me = useSignedInUser();
  if (me.role === "athlete" && !me.onboarding_completed) return <Navigate to={paths.onboarding} replace />;
  const today = localDay(new Date(), me.timezone, i18n.language).isoDate;

  return (
    <article className="max-w-[40rem]">
      {me.role === "athlete" && <CalendarNav />}
      <h1 className="font-display text-step-4 font-bold">{t("body.title")}</h1>
      {me.role === "coach" ? (
        // A coach has no weigh-ins of their own; the athlete view arrives with the coach dashboard (#48).
        <p className="mt-6 border-l-4 border-iron pl-3">{t("body.coachNotice")}</p>
      ) : (
        <BodyTracking athleteId={me.id} units={me.units} today={today} canLog />
      )}
    </article>
  );
}
