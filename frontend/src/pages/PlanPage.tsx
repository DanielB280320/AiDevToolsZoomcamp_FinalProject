import { useTranslation } from "react-i18next";
import { Navigate } from "react-router";

import { useSignedInUser } from "../components/RequireAuth";
import { CalendarNav } from "../features/calendar/CalendarNav";
import { PlanEditor } from "../features/plan/PlanEditor";
import { paths } from "../paths";

/** Plan editor (spec F8, custom mode). Athlete only for now (D75(8)); coach editing arrives with #46/#47. */
export function PlanPage() {
  const { t } = useTranslation();
  const me = useSignedInUser();
  if (me.role === "athlete" && !me.onboarding_completed) return <Navigate to={paths.onboarding} replace />;

  return (
    <article className="max-w-[40rem]">
      {me.role === "athlete" && <CalendarNav />}
      <h1 className="font-display text-step-4 font-bold">{t("plan.title")}</h1>
      {me.role === "athlete" ? <PlanEditor me={me} /> : <p className="mt-6 border-l-4 border-iron pl-3">{t("plan.coachNotice")}</p>}
    </article>
  );
}
