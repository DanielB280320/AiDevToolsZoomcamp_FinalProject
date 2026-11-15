import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type Plan,
  type PlanChangeSummary,
  type PlanSummary,
  useActivatePlan,
  useDeletePlan,
  usePlans,
  usePlanVersion,
  usePlanVersions,
} from "../../api/plan";
import type { UnitSystem } from "../../lib/units";
import { BUTTON, PRIMARY } from "./fields";
import { PlanView } from "./PlanView";
import type { Viewer } from "./PlanSummary";

type Props = {
  athleteId: string;
  units: UnitSystem;
  timezone: string;
  viewer?: Viewer;
  /** Unsaved edits in the Training or Meals tab: making another plan current discards them. */
  unsaved?: boolean;
  /** A previous plan was made current: the editor rebuilds its drafts from it. */
  onActivated?: (plan: Plan) => void;
};

type Pending = { kind: "activate" | "delete"; plan: PlanSummary };

/**
 * History of the athlete's plans (F8.2, F8.3, D106): one row per plan, newest first. Opening a
 * plan shows its changes over time; opening a change shows the plan as it was after it (read-only).
 */
export function VersionHistory({ athleteId, units, timezone, viewer = "athlete", unsaved = false, onActivated }: Props) {
  const { t, i18n } = useTranslation();
  const [pending, setPending] = useState<Pending | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const activate = useActivatePlan(athleteId);
  const remove = useDeletePlan(athleteId);
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

  const ask = (kind: Pending["kind"], target: PlanSummary) => {
    activate.reset();
    remove.reset();
    setNotice(null);
    setPending({ kind, plan: target });
  };
  const confirm = () => {
    if (!pending) return;
    const { kind, plan: target } = pending;
    const name = planName(target);
    setNotice(null);
    if (kind === "activate") {
      activate.mutate(target.plan_no, {
        onSuccess: (next) => {
          setPending(null);
          setNotice(t("plan.history.madeCurrentDone", { name }));
          onActivated?.(next);
        },
      });
    } else {
      remove.mutate(target.plan_no, {
        onSuccess: () => {
          setPending(null);
          setNotice(t("plan.history.deletedDone", { name }));
        },
      });
    }
  };
  const busy = activate.isPending || remove.isPending;
  const failed = pending?.kind === "activate" ? activate.isError : remove.isError;

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
      <div role="status" aria-live="polite">
        {notice && <p className="mb-3 font-semibold text-spruce-dark">{notice}</p>}
      </div>
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
            <div className="mt-2 flex flex-wrap gap-2">
              <button
                type="button"
                className={BUTTON}
                onClick={() => setPlanNo(p.plan_no)}
                aria-label={t("plan.history.openPlan", { name: planName(p) })}
              >
                {t("plan.history.openButton")}
              </button>
              {!p.active && (
                <>
                  <button
                    type="button"
                    className={BUTTON}
                    onClick={() => ask("activate", p)}
                    aria-label={t("plan.history.makeCurrentFor", { name: planName(p) })}
                  >
                    {t("plan.history.makeCurrent")}
                  </button>
                  <button
                    type="button"
                    className={`${BUTTON} border-alert text-alert`}
                    onClick={() => ask("delete", p)}
                    aria-label={t("plan.history.deleteFor", { name: planName(p) })}
                  >
                    {t("plan.history.delete")}
                  </button>
                </>
              )}
            </div>
            {pending?.plan.plan_no === p.plan_no && (
              <div role="alertdialog" aria-label={t(`plan.history.confirm.${pending.kind}Title`, { name: planName(p) })} className="mt-3 border-l-4 border-iron pl-3">
                <p className="font-semibold">{t(`plan.history.confirm.${pending.kind}Title`, { name: planName(p) })}</p>
                <p className="mt-1">{t(`plan.history.confirm.${pending.kind}Body`)}</p>
                {pending.kind === "activate" && unsaved && <p className="mt-1">{t("plan.newPlan.unsaved")}</p>}
                {failed && <p role="alert" className="mt-1 font-semibold text-alert">{t(`plan.history.confirm.${pending.kind}Failed`)}</p>}
                <div className="mt-2 flex flex-wrap gap-2">
                  <button type="button" className={PRIMARY} disabled={busy} onClick={confirm}>
                    {t(`plan.history.confirm.${pending.kind}Yes`)}
                  </button>
                  <button type="button" className={BUTTON} disabled={busy} onClick={() => setPending(null)}>
                    {t("plan.history.confirm.cancel")}
                  </button>
                </div>
              </div>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
