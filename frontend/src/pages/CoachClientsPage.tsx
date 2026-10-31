import { useTranslation } from "react-i18next";
import { Navigate } from "react-router";

import { useSignedInUser } from "../components/RequireAuth";
import { ClientList } from "../features/coach/ClientList";
import { CoachNav } from "../features/coach/CoachNav";
import { paths } from "../paths";

/** Coach client list (spec F16, F16.5): athletes who need attention first. Athletes go to Today. */
export function CoachClientsPage() {
  const { t } = useTranslation();
  const me = useSignedInUser();
  if (me.role !== "coach") return <Navigate to={paths.today} replace />;
  return (
    <article className="min-w-0 max-w-5xl">
      <CoachNav />
      <h1 className="font-display text-step-4 font-bold">{t("coach.clients.title")}</h1>
      <p className="mt-1 max-w-[60ch] text-slate">{t("coach.clients.lead")}</p>
      <ClientList />
    </article>
  );
}
