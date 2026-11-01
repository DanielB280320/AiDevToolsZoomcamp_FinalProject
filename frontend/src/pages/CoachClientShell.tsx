import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, Navigate, Outlet, useParams } from "react-router";

import { coachAthletesKey, useCoachAthletes } from "../api/coach";
import { isApiError } from "../api/errors";
import { useSignedInUser } from "../components/RequireAuth";
import { QueryState } from "../features/calendar/QueryState";
import { ClientNav } from "../features/coach/ClientNav";
import type { ClientScope } from "../features/coach/clientScope";
import { paths } from "../paths";

function NotLinked() {
  const { t } = useTranslation();
  return (
    <article className="max-w-[40rem]" data-testid="not-linked">
      <h1 className="font-display text-step-3 font-bold">{t("coach.client.notLinked.title")}</h1>
      <p role="alert" className="mt-3 border-l-4 border-iron pl-3">
        {t("coach.client.notLinked.body")}
      </p>
      <p className="mt-4">
        <Link to={paths.coachClients} className="inline-flex min-h-11 items-center font-semibold text-spruce underline underline-offset-4">
          {t("coach.client.back")}
        </Link>
      </p>
    </article>
  );
}

/**
 * Any request of the coach context that answers `403 not_linked` (the link ended after the list
 * loaded, or the id was never linked) turns the shell into the not-linked page and drops the
 * cached client list, so the ended client disappears from it too. Watching the query and mutation
 * caches covers every view, present and future, without each one handling the error.
 */
function useNotLinkedGuard(athleteId: string | undefined): boolean {
  const queryClient = useQueryClient();
  const [hit, setHit] = useState<string | null>(null);
  useEffect(() => {
    const onError = (error: unknown) => {
      if (isApiError(error) && error.problem.code === "not_linked") {
        setHit(athleteId ?? "");
        void queryClient.invalidateQueries({ queryKey: coachAthletesKey });
      }
    };
    const unsubscribeQueries = queryClient.getQueryCache().subscribe((event) => {
      if (event.type === "updated" && event.action.type === "error") onError(event.action.error);
    });
    const unsubscribeMutations = queryClient.getMutationCache().subscribe((event) => {
      if (event.type === "updated" && event.action.type === "error") onError(event.action.error);
    });
    return () => {
      unsubscribeQueries();
      unsubscribeMutations();
    };
  }, [queryClient, athleteId]);
  return hit !== null && hit === (athleteId ?? "");
}

/**
 * Coach context (spec F16): a persistent banner with the client's name and a way back, the
 * client's tabs, and the client's views below. The client comes from the list of actively linked
 * athletes, so an id that is not (or no longer) linked shows the not-linked page and loads no data.
 */
export function CoachClientShell() {
  const { t } = useTranslation();
  const me = useSignedInUser();
  const { athleteId } = useParams();
  const clients = useCoachAthletes(me.role === "coach");
  const notLinked = useNotLinkedGuard(athleteId);
  if (me.role !== "coach") return <Navigate to={paths.today} replace />;
  if (!clients.data) {
    return <QueryState isPending={clients.isPending} isError={clients.isError} onRetry={() => void clients.refetch()} />;
  }
  const client = clients.data.find((c) => c.athlete.id === athleteId);
  if (!client || notLinked) return <NotLinked />;
  const scope: ClientScope = {
    athleteId: client.athlete.id,
    displayName: client.athlete.display_name,
    units: client.units,
    timezone: client.timezone,
  };
  return (
    <div className="min-w-0 max-w-[40rem]">
      <div
        role="region"
        aria-label={t("coach.client.bannerLabel")}
        className="mb-4 flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-l-8 border-plate bg-line px-3 py-2"
      >
        <p className="min-w-0 break-words font-display text-step-1 font-bold">
          {t("coach.client.viewing", { name: scope.displayName })}
        </p>
        <Link to={paths.coachClients} className="inline-flex min-h-11 items-center font-semibold text-spruce underline underline-offset-4">
          {t("coach.client.back")}
        </Link>
      </div>
      <ClientNav athleteId={scope.athleteId} />
      <Outlet context={scope} />
    </div>
  );
}
