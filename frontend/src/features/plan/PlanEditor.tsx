import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";

import { type Plan, usePlan } from "../../api/plan";
import type { Me } from "../../api/session";
import { QueryState } from "../calendar/QueryState";
import {
  DumbbellIcon,
  HistoryIcon,
  UtensilsIcon,
} from "../../components/icons";
import { BUTTON } from "./fields";
import { MealEditor } from "./MealEditor";
import { NewPlanForm } from "./NewPlanForm";
import { PlanSummary, type Viewer } from "./PlanSummary";
import { TrainingEditor } from "./TrainingEditor";
import { VersionHistory } from "./VersionHistory";

/** Whose plan is edited: the signed-in athlete, or a client in the coach context (F8, F16). */
export type PlanOwner = Pick<Me, "id" | "units" | "timezone">;

type Tab = "training" | "meals" | "history";
const TABS: Tab[] = ["training", "meals", "history"];
const TRAINING: Tab = TABS[0]!;
const MEALS: Tab = TABS[1]!;
const HISTORY: Tab = TABS[2]!;
const TAB_ICON = {
  training: DumbbellIcon,
  meals: UtensilsIcon,
  history: HistoryIcon,
};

function TabAbout({ tab, viewer }: { tab: Tab; viewer: Viewer }) {
  const { t } = useTranslation();
  return (
    <p className="mb-3 text-step--1 text-slate">
      {t(`plan.tabAbout.${tab}.${viewer}`)}
    </p>
  );
}

function Editor({
  plan,
  me,
  viewer,
}: {
  plan: Plan;
  me: PlanOwner;
  viewer: Viewer;
}) {
  const { t } = useTranslation();
  const [tab, setTab] = useState<Tab>("training");
  // A new epoch rebuilds both drafts from the latest plan (after a save, a reload or a regeneration).
  const [epoch, setEpoch] = useState(0);
  const [base, setBase] = useState(plan.revision);
  const [conflict, setConflict] = useState(false);
  const [dirty, setDirty] = useState({ training: false, meals: false });
  const [created, setCreated] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  // Revision of a plan just created: its drafts are rebuilt once the cached plan is that one (it may land a render after the response).
  const [createdRevision, setCreatedRevision] = useState<number | null>(null);

  const fresh = (next: Plan) => {
    setBase(next.revision);
    setConflict(false);
    setEpoch((n) => n + 1);
  };
  const rebuilt = createdRevision !== null && plan.revision === createdRevision ? "new" : "old";
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
      setCreated(null);
      setSaved(true);
      fresh(next);
    },
    onDiscard: () => fresh(plan),
  };

  return (
    <div>
      <p
        className="mt-2 text-step--1 text-slate"
        data-testid="plan-description"
      >
        {t(`plan.about.${viewer}`)}
      </p>
      <div role="status" aria-live="polite">
        {saved && (
          <p className="mt-2 font-semibold text-spruce-dark">
            {t("plan.saved")}
          </p>
        )}
        {created !== null && (
          <p className="mt-2 font-semibold text-spruce-dark">
            {t("plan.newPlan.done", { name: created })}
          </p>
        )}
      </div>
      <PlanSummary plan={plan} timezone={me.timezone} viewer={viewer} />

      {conflict && (
        <div role="alert" className="mt-4 border-l-4 border-alert pl-3">
          <p className="font-semibold">{t("plan.conflict.title")}</p>
          <p>{t("plan.conflict.body")}</p>
          <button type="button" className={`${BUTTON} mt-2`} onClick={() => fresh(plan)}>
            {t("plan.conflict.reload")}
          </button>
        </div>
      )}

      <div
        role="tablist"
        aria-label={t("plan.tabs.label")}
        className="mt-4 flex border-b-4 border-iron"
      >
        {TABS.map((id) => {
          const Icon = TAB_ICON[id];
          return (
            <button
              key={id}
              role="tab"
              type="button"
              id={`plan-tab-${id}`}
              aria-selected={tab === id}
              aria-controls="plan-panel"
              onClick={() => setTab(id)}
              className={`flex min-h-12 flex-1 items-center justify-center gap-2 px-2 font-display text-step-1 font-bold sm:flex-none sm:px-5 ${tab === id ? "bg-iron text-chalk" : "text-iron hover:bg-line"}`}
            >
              <Icon className="size-5" />
              {t(`plan.tabs.${id}`)}
            </button>
          );
        })}
      </div>

      {/* Both editors stay mounted so switching tabs never loses a draft. */}
      <div id="plan-panel" role="tabpanel" aria-labelledby={`plan-tab-${tab}`} className="mt-4">
        <div hidden={tab !== "training"}>
          <TabAbout tab={TRAINING} viewer={viewer} />
          <TrainingEditor
            key={`t-${epoch}-${rebuilt}`}
            {...shared}
            units={me.units}
            blocked={dirty.meals}
            onDirtyChange={onTrainingDirty}
          />
        </div>
        <div hidden={tab !== "meals"}>
          <TabAbout tab={MEALS} viewer={viewer} />
          <MealEditor
            key={`m-${epoch}-${rebuilt}`}
            {...shared}
            blocked={dirty.training}
            onDirtyChange={onMealsDirty}
          />
        </div>
        {tab === "history" && (
          <>
            <TabAbout tab={HISTORY} viewer={viewer} />
            <VersionHistory
              athleteId={me.id}
              units={me.units}
              timezone={me.timezone}
            />
          </>
        )}
      </div>

      <NewPlanForm
        athleteId={me.id}
        timezone={me.timezone}
        unsaved={dirty.training || dirty.meals}
        onCreated={(next) => {
          setSaved(false);
          setCreated(next.name);
          setCreatedRevision(next.revision);
          setBase(next.revision);
          setConflict(false);
          setEpoch((n) => n + 1);
        }}
      />
    </div>
  );
}

/** The plan editor of the signed-in athlete (F8). Coaches get a notice only until coach editing lands (D75(8)). */
export function PlanEditor({
  me,
  viewer = "athlete",
}: {
  me: PlanOwner;
  viewer?: Viewer;
}) {
  const { t } = useTranslation();
  const query = usePlan(me.id);
  if (!query.data) return <QueryState isPending={query.isPending} isError={query.isError} onRetry={() => void query.refetch()} />;
  return (
    <>
      <Editor plan={query.data} me={me} viewer={viewer} />
      {query.isFetching && <span className="sr-only">{t("plan.loading")}</span>}
    </>
  );
}
