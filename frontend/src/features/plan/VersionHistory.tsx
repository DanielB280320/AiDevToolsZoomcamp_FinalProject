import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type PlanChangeSummary,
  type PlanSummary,
  usePlans,
  usePlanVersion,
  usePlanVersions,
} from "../../api/plan";
import type { UnitSystem } from "../../lib/units";
import { BUTTON } from "./fields";
import { PlanView } from "./PlanView";
import type { Viewer } from "./PlanSummary";

type Props = {
  athleteId: string;
  units: UnitSystem;
  timezone: string;
  viewer?: Viewer;
};

/**
 * History of the athlete's plans (F8.2, F8.3, D106): one row per plan, newest first. Opening a
 * plan shows its changes over time; opening a change shows the plan as it was after it (read-only).
 */
export function VersionHistory({ athleteId, units, timezone, viewer = "athlete" }: Props) {
  const { t, i18n } = useTranslation();
  const [planNo, setPlanNo] = useState<number | null>(null);
  const [version, setVersion] = useState<number | null>(null);
  const plans = usePlans(athleteId);
  const timeline = usePlanVersions(athleteId, planNo);
  const snapshot = usePlanVersion(athleteId, version);

  const dateTime = (iso: string) =>
    new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium", timeStyle: "short", timeZone: timezone }).format(
      new Date(iso),
    );
  const day = (iso: string) =>
    new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium", timeZone: "UTC" }).format(
      new Date(`${iso}T00:00:00Z`),
    );
  const planName = (plan: Pick<PlanSummary, "name" | "plan_no">) =>
    plan.name ?? t("plan.history.planFallback", { number: plan.plan_no });
  const author = (change: PlanChangeSummary): string => {
    if (change.author_role === "athlete") return t(viewer === "coach" ? "plan.history.authors.client" : "plan.history.authors.you");
    if (change.author_role === "coach") {
      return change.author?.display_name
        ? t("plan.history.authors.coach", { name: change.author.display_name })
        : t("plan.history.authors.coachUnknown");
    }
    return t("plan.history.authors.unknown");
  };

  const plan = plans.data?.find((p) => p.plan_no === planNo) ?? null;

  if (planNo !== null && version !== null) {
    const entry = timeline.data?.find((v) => v.version === version);
    const name = plan ? planName(plan) : t("plan.history.planFallback", { number: planNo });
    const when = entry ? dateTime(entry.change.at) : "";
    return (
      <section aria-label={t("plan.history.snapshotLabel", { name, date: when })}>
        <button type="button" className={BUTTON} onClick={() => setVersion(null)}>
          {t("plan.history.backToChanges")}
        </button>
        <h3 className="mt-4 break-words font-display text-step-2 font-bold">
          {t("plan.history.snapshotTitle", { name, date: when })}
        </h3>
        {entry && <p className="mt-1 text-step--1">{`${t(`plan.history.kinds.${entry.change.kind}`)}, ${author(entry.change)}`}</p>}
        <p className="mt-1 border-l-4 border-iron pl-3">{t("plan.history.readOnly")}</p>
        {snapshot.isPending && <p role="status">{t("plan.loading")}</p>}
        {snapshot.isError && <p role="alert" className="font-semibold text-alert">{t("plan.history.failed")}</p>}
        {snapshot.data && (
          <div className="mt-4">
            <PlanView plan={snapshot.data} units={units} />
          </div>
        )}
      </section>
    );
  }

  if (planNo !== null) {
    const name = plan ? planName(plan) : t("plan.history.planFallback", { number: planNo });
    return (
      <section aria-label={t("plan.history.timeline", { name })}>
        <button type="button" className={BUTTON} onClick={() => setPlanNo(null)}>
          {t("plan.history.backToPlans")}
        </button>
        <h3 className="mt-4 break-words font-display text-step-2 font-bold">{name}</h3>
        <h4 className="mt-2 font-display text-step-1 font-bold">{t("plan.history.timelineTitle")}</h4>
        {plan && plan.changes === 0 && <p className="mt-1 text-slate">{t("plan.history.noChanges")}</p>}
        {timeline.isPending && <p role="status">{t("plan.loading")}</p>}
        {timeline.isError && <p role="alert" className="font-semibold text-alert">{t("plan.history.failed")}</p>}
        <ol className="mt-3 flex flex-col gap-3" data-testid="plan-timeline">
          {(timeline.data ?? []).map((v) => {
            const kind = t(`plan.history.kinds.${v.change.kind}`);
            const date = dateTime(v.change.at);
            return (
              <li key={v.id} className="border-2 border-iron/30 p-3">
                <p className="font-semibold">{kind}</p>
                <p className="text-step--1">{`${date}, ${author(v.change)}`}</p>
                <button
                  type="button"
                  className={`${BUTTON} mt-2`}
                  onClick={() => setVersion(v.version)}
                  aria-label={t("plan.history.openChange", { kind, date })}
                >
                  {t("plan.history.openButton")}
                </button>
              </li>
            );
          })}
        </ol>
      </section>
    );
  }

  return (
    <section aria-label={t("plan.tabs.history")}>
      {plans.isPending && <p role="status">{t("plan.loading")}</p>}
      {plans.isError && <p role="alert" className="font-semibold text-alert">{t("plan.history.failed")}</p>}
      {plans.data?.length === 0 && <p className="text-slate">{t("plan.history.empty")}</p>}
      <ul className="flex flex-col gap-3">
        {(plans.data ?? []).map((p) => (
          <li key={p.plan_no} className="border-2 border-iron/30 p-3">
            <p className="break-words font-display text-step-1 font-bold">
              {planName(p)}
              {p.active && <span className="ml-2 text-step--1 font-semibold text-spruce-dark">{t("plan.history.current")}</span>}
            </p>
            <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 text-step--1">
              {p.start_date && (
                <>
                  <dt className="font-semibold">{t("plan.history.started")}</dt>
                  <dd>{day(p.start_date)}</dd>
                </>
              )}
              <dt className="font-semibold">{t("plan.history.created")}</dt>
              <dd>{dateTime(p.created_at)}</dd>
              <dt className="font-semibold">{t("plan.history.changes")}</dt>
              <dd>{t("plan.history.changesValue", { count: p.changes })}</dd>
              {p.changes > 0 && (
                <>
                  <dt className="font-semibold">{t("plan.history.lastChange")}</dt>
                  <dd>{dateTime(p.last_changed_at)}</dd>
                </>
              )}
            </dl>
            <button
              type="button"
              className={`${BUTTON} mt-2`}
              onClick={() => setPlanNo(p.plan_no)}
              aria-label={t("plan.history.openPlan", { name: planName(p) })}
            >
              {t("plan.history.openButton")}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
