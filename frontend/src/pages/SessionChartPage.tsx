import { useTranslation } from "react-i18next";
import { Link, Navigate, useParams } from "react-router";

import { useSignedInUser } from "../components/RequireAuth";
import { SessionChartView } from "../features/charts/SessionChartView";
import { SessionNotes } from "../features/notes/SessionNotes";
import { paths } from "../paths";

/** `/progress/session/:sessionId` (spec F15.2): target vs. actual per set of one session. */
export function SessionChartPage() {
  const { t } = useTranslation();
  const me = useSignedInUser();
  const { sessionId } = useParams();
  if (!sessionId || me.role !== "athlete") return <Navigate to={paths.progress} replace />;
  return (
    <article className="min-w-0 max-w-[40rem]">
      <Link to={paths.progress} className="font-semibold text-spruce underline underline-offset-4">
        {t("charts.session.back")}
      </Link>
      <h1 className="mt-3 font-display text-step-4 font-bold">{t("charts.session.title")}</h1>
      <div className="mt-4 min-w-0">
        <SessionChartView athleteId={me.id} sessionId={sessionId} units={me.units} />
      </div>
      <SessionNotes athleteId={me.id} sessionId={sessionId} />
    </article>
  );
}
