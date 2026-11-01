import { useTranslation } from "react-i18next";
import { Link, Navigate } from "react-router";

import { useSignedInUser } from "../components/RequireAuth";
import { CalendarNav } from "../features/calendar/CalendarNav";
import { ProgressView } from "../features/charts/ProgressView";
import { localDay } from "../lib/today";
import { paths } from "../paths";

/** Progress charts (spec F15) of the signed-in athlete; a coach opens them from a client (F16). */
export function ProgressPage() {
  const { t, i18n } = useTranslation();
  const me = useSignedInUser();
  if (me.role === "athlete" && !me.onboarding_completed) return <Navigate to={paths.onboarding} replace />;
  const today = localDay(new Date(), me.timezone, i18n.language).isoDate;

  return (
    <article className="min-w-0 max-w-[40rem]">
      {me.role === "athlete" && <CalendarNav />}
      <h1 className="font-display text-step-4 font-bold">{t("charts.title")}</h1>
      {me.role === "coach" ? (
        <p className="mt-6 border-l-4 border-iron pl-3">
          {t("charts.coachNotice")}{" "}
          <Link to={paths.coachClients} className="font-semibold">
            {t("coach.clients.title")}
          </Link>
        </p>
      ) : (
        <ProgressView athleteId={me.id} units={me.units} today={today} />
      )}
    </article>
  );
}
