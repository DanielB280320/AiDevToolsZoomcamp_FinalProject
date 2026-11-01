import { useTranslation } from "react-i18next";
import { Link, Navigate, useParams } from "react-router";

import { BodyTracking } from "../features/body/BodyTracking";
import { MonthView } from "../features/calendar/MonthView";
import { TodayView } from "../features/calendar/TodayView";
import { WeekView } from "../features/calendar/WeekView";
import { ProgressView } from "../features/charts/ProgressView";
import { SessionChartView } from "../features/charts/SessionChartView";
import { ClientProfile } from "../features/coach/ClientProfile";
import { useClientScope } from "../features/coach/clientScope";
import { PlanEditor } from "../features/plan/PlanEditor";
import { localDay } from "../lib/today";
import { paths } from "../paths";

/*
 * The client's views in the coach context (F16, F15, F9, F8). Each one reuses the athlete's view
 * component with the client's id, units and time zone; there is no logging control anywhere in
 * here (F16.4) and no request uses `me`.
 */

function Heading({ children }: { children: string }) {
  return <h1 className="font-display text-step-3 font-bold">{children}</h1>;
}

export function CoachClientTodayPage() {
  const { t, i18n } = useTranslation();
  const scope = useClientScope();
  const today = localDay(new Date(), scope.timezone, i18n.language);
  return (
    <article>
      <h1 className="font-display font-bold">
        <time dateTime={today.isoDate} className="block">
          <span className="block text-step-4 leading-none">{today.weekday}</span>
          <span className="mt-1 block text-step-2 font-semibold leading-tight text-slate">{today.date}</span>
        </time>
        <span className="sr-only">{t("coach.client.tabs.today")}</span>
      </h1>
      <TodayView
        me={{ id: scope.athleteId, units: scope.units }}
        readOnly
        sessionLink={(sessionId) => paths.coachClient(scope.athleteId, `/progress/session/${sessionId}`)}
      />
    </article>
  );
}

export function CoachClientWeekPage() {
  const scope = useClientScope();
  const weekPath = paths.coachClient(scope.athleteId, "/week");
  return (
    <WeekView
      athleteId={scope.athleteId}
      timezone={scope.timezone}
      basePath={weekPath}
      readOnly
      sessionLink={(sessionId) => paths.coachClient(scope.athleteId, `/progress/session/${sessionId}`)}
    />
  );
}

export function CoachClientMonthPage() {
  const scope = useClientScope();
  const monthPath = paths.coachClient(scope.athleteId, "/month");
  const weekPath = paths.coachClient(scope.athleteId, "/week");
  return (
    <MonthView
      athleteId={scope.athleteId}
      timezone={scope.timezone}
      monthPath={monthPath}
      weekPath={weekPath}
    />
  );
}

export function CoachClientBodyPage() {
  const { t, i18n } = useTranslation();
  const scope = useClientScope();
  const today = localDay(new Date(), scope.timezone, i18n.language).isoDate;
  return (
    <article>
      <Heading>{t("body.title")}</Heading>
      <BodyTracking athleteId={scope.athleteId} units={scope.units} today={today} canLog={false} />
    </article>
  );
}

export function CoachClientPlanPage() {
  const { t } = useTranslation();
  const scope = useClientScope();
  return (
    <article>
      <Heading>{t("plan.title")}</Heading>
      <PlanEditor me={{ id: scope.athleteId, units: scope.units, timezone: scope.timezone }} />
    </article>
  );
}

export function CoachClientProgressPage() {
  const { t, i18n } = useTranslation();
  const scope = useClientScope();
  const today = localDay(new Date(), scope.timezone, i18n.language).isoDate;
  return (
    <article className="min-w-0">
      <Heading>{t("charts.title")}</Heading>
      <ProgressView athleteId={scope.athleteId} units={scope.units} today={today} />
    </article>
  );
}

export function CoachClientSessionPage() {
  const { t } = useTranslation();
  const scope = useClientScope();
  const { sessionId } = useParams();
  if (!sessionId) return <Navigate to={paths.coachClient(scope.athleteId, "/progress")} replace />;
  return (
    <article className="min-w-0">
      <Link
        to={paths.coachClient(scope.athleteId, "/progress")}
        className="inline-flex min-h-11 items-center font-semibold text-spruce underline underline-offset-4"
      >
        {t("charts.session.back")}
      </Link>
      <Heading>{t("charts.session.title")}</Heading>
      <div className="mt-4 min-w-0">
        <SessionChartView athleteId={scope.athleteId} sessionId={sessionId} units={scope.units} />
      </div>
    </article>
  );
}

export function CoachClientProfilePage() {
  const { t } = useTranslation();
  const scope = useClientScope();
  return (
    <article>
      <Heading>{t("coach.client.tabs.profile")}</Heading>
      <ClientProfile athleteId={scope.athleteId} units={scope.units} />
    </article>
  );
}
