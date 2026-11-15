import { useTranslation } from "react-i18next";

import { SelectInput } from "./fields";
import { TRAINING_GOALS, type TrainingGoal } from "./trainingGoal";

/** The plan's training goal (D107): what the plan trains for, shown with a one-line description. */
export function GoalSelect({
  id,
  value,
  onChange,
}: {
  id: string;
  value: TrainingGoal;
  onChange: (goal: TrainingGoal) => void;
}) {
  const { t } = useTranslation();
  return (
    <div>
      <SelectInput
        id={id}
        label={t("plan.goal.label")}
        value={value}
        onChange={(next) => onChange(next as TrainingGoal)}
        options={TRAINING_GOALS.map((goal) => ({ value: goal, label: t(`plan.goal.options.${goal}`) }))}
        hint={t("plan.goal.hint")}
      />
      <p className="mt-1 text-step--1 font-semibold" data-testid="goal-detail">
        {t(`plan.goal.details.${value}`)}
      </p>
    </div>
  );
}
