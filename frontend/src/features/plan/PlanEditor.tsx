import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";

import { type Plan, usePlan, useRegeneratePlan } from "../../api/plan";
import type { Me } from "../../api/session";
import { QueryState } from "../calendar/QueryState";
import { BUTTON, PRIMARY } from "./fields";
import { MealEditor } from "./MealEditor";
import { TrainingEditor } from "./TrainingEditor";
import { VersionHistory } from "./VersionHistory";

type Tab = "training" | "meals" | "history";
const TABS: Tab[] = ["training", "meals", "history"];

function Editor({ plan, me }: { plan: Plan; me: Me }) {
  const { t } = useTranslation();
  const [tab, setTab] = useState<Tab>("training");
  // A new epoch rebuilds both drafts from the latest plan (after a save, a reload or a regeneration).
  const [epoch, setEpoch] = useState(0);
  const [base, setBase] = useState(plan.revision);
  const [conflict, setConflict] = useState(false);
  const [dirty, setDirty] = useState({ training: false, meals: false });
  const [confirming, setConfirming] = useState(false);
  const [regenerated, setRegenerated] = useState(false);
  const [saved, setSaved] = useState(false);
  const regenerate = useRegeneratePlan(me.id);

  const fresh = (next: Plan) => {
    setBase(next.revision);
    setConflict(false);
    setEpoch((n) => n + 1);
  };
  const onTrainingDirty = useCallback((training: boolean) => {
    setDirty((d) => ({ ...d, training }));
    if (training) setSaved(false);
  }, []);
  const onMealsDirty = useCallback((meals: boolean) => {
    setDirty((d) => ({ ...d, meals }));
    if (meals) setSaved(false);
  }, []);
  const shared = {
    plan,
    athleteId: me.id,
    baseRevision: base,
    conflict,
    onConflict: () => setConflict(true),
    onSaved: (next: Plan) => {
      setRegenerated(false);
      setSaved(true);
      fresh(next);
    },
    onDiscard: () => fresh(plan),
  };

  return (
    <div>
      <div role="status" aria-live="polite">
        {saved && <p className="font-semibold text-spruce-dark">{t("plan.saved")}</p>}
      </div>
      <p className="text-step--1 text-slate">
        {t("plan.status", { version: plan.version, source: t(`plan.history.sources.${plan.source}`) })}
      </p>

      {conflict && (
        <div role="alert" className="mt-4 border-l-4 border-alert pl-3">
          <p className="font-semibold">{t("plan.conflict.title")}</p>
          <p>{t("plan.conflict.body")}</p>
          <button type="button" className={`${BUTTON} mt-2`} onClick={() => fresh(plan)}>
            {t("plan.conflict.reload")}
          </button>
        </div>
      )}

      <div role="tablist" aria-label={t("plan.tabs.label")} className="mt-4 flex border-b-4 border-iron">
        {TABS.map((id) => (
          <button
            key={id}
            role="tab"
            type="button"
            id={`plan-tab-${id}`}
            aria-selected={tab === id}
            aria-controls="plan-panel"
            onClick={() => setTab(id)}
            className={`min-h-12 flex-1 px-2 font-display text-step-1 font-bold sm:flex-none sm:px-5 ${tab === id ? "bg-iron text-chalk" : "text-iron hover:bg-line"}`}
          >
            {t(`plan.tabs.${id}`)}
          </button>
        ))}
      </div>

      {/* Both editors stay mounted so switching tabs never loses a draft. */}
      <div id="plan-panel" role="tabpanel" aria-labelledby={`plan-tab-${tab}`} className="mt-4">
        <div hidden={tab !== "training"}>
          <TrainingEditor key={`t-${epoch}`} {...shared} units={me.units} blocked={dirty.meals} onDirtyChange={onTrainingDirty} />
        </div>
        <div hidden={tab !== "meals"}>
          <MealEditor key={`m-${epoch}`} {...shared} blocked={dirty.training} onDirtyChange={onMealsDirty} />
        </div>
        {tab === "history" && <VersionHistory athleteId={me.id} units={me.units} timezone={me.timezone} />}
      </div>

      <section aria-label={t("plan.regenerate.title")} className="mt-8 border-t-4 border-iron pt-4">
        <h2 className="font-display text-step-2 font-bold">{t("plan.regenerate.title")}</h2>
        <p className="mt-1 max-w-[52ch]">{t("plan.regenerate.lead")}</p>
        {!confirming && (
          <button type="button" className={`${BUTTON} mt-3`} onClick={() => setConfirming(true)}>
            {t("plan.regenerate.button")}
          </button>
        )}
        {confirming && (
          <div role="alertdialog" aria-labelledby="regen-title" aria-describedby="regen-body" className="mt-3 border-2 border-iron p-3">
            <p id="regen-title" className="font-semibold">
              {t("plan.regenerate.confirmTitle")}
            </p>
            <p id="regen-body" className="mt-1">
              {t("plan.regenerate.confirmBody")}
            </p>
            {(dirty.training || dirty.meals) && <p className="mt-1 font-semibold">{t("plan.regenerate.unsaved")}</p>}
            <div className="mt-3 flex flex-wrap gap-3">
              <button
                type="button"
                className={PRIMARY}
                disabled={regenerate.isPending}
                onClick={() =>
                  regenerate.mutate(
                    { scope: "all" },
                    {
                      onSuccess: (next) => {
                        setConfirming(false);
                        setRegenerated(true);
                        fresh(next);
                      },
                    },
                  )
                }
              >
                {t("plan.regenerate.confirm")}
              </button>
              <button type="button" className={BUTTON} onClick={() => setConfirming(false)}>
                {t("plan.cancel")}
              </button>
            </div>
          </div>
        )}
        <div role="status" aria-live="polite">
          {regenerated && <p className="mt-2 font-semibold text-spruce-dark">{t("plan.regenerate.done")}</p>}
        </div>
        {regenerate.isError && (
          <p role="alert" className="mt-2 font-semibold text-alert">
            {t("plan.regenerate.failed")}
          </p>
        )}
      </section>
    </div>
  );
}

/** The plan editor of the signed-in athlete (F8). Coaches get a notice only until coach editing lands (D75(8)). */
export function PlanEditor({ me }: { me: Me }) {
  const { t } = useTranslation();
  const query = usePlan(me.id);
  if (!query.data) return <QueryState isPending={query.isPending} isError={query.isError} onRetry={() => void query.refetch()} />;
  return (
    <>
      <Editor plan={query.data} me={me} />
      {query.isFetching && <span className="sr-only">{t("plan.loading")}</span>}
    </>
  );
}
