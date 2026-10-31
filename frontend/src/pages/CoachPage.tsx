import { useTranslation } from "react-i18next";
import { Navigate } from "react-router";

import { useSignedInUser } from "../components/RequireAuth";
import { CalendarNav } from "../features/calendar/CalendarNav";
import { AthleteCoach } from "../features/coach/AthleteCoach";
import { CoachPanel } from "../features/coach/CoachPanel";
import { paths } from "../paths";

/** Coach linking (spec F16): athletes find and request a coach; coaches manage profile and requests. */
export function CoachPage() {
  const { t } = useTranslation();
  const me = useSignedInUser();
  if (me.role === "athlete" && !me.onboarding_completed) return <Navigate to={paths.onboarding} replace />;
  return (
    <article className="max-w-[40rem]">
      {me.role === "athlete" && <CalendarNav />}
      <h1 className="font-display text-step-4 font-bold">{t("coach.title")}</h1>
      {me.role === "athlete" ? <AthleteCoach /> : <CoachPanel />}
    </article>
  );
}
