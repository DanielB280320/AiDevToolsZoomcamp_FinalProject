import type { AthleteProfile } from "../../api/athlete";
import type { Plan } from "../../api/plan";

export type TrainingGoal = Plan["training_goal"];
export type RepRange = Plan["rep_ranges"][TrainingGoal];

export const TRAINING_GOALS: readonly TrainingGoal[] = ["strength", "hypertrophy", "endurance", "maintenance", "cutting"];

/** The default training goal for a profile goal (D107); the backend applies the same mapping. */
const BY_PROFILE_GOAL: Record<AthleteProfile["goal"], TrainingGoal> = {
  muscle_gain: "hypertrophy",
  cutting: "cutting",
  maintenance: "maintenance",
  recomposition: "hypertrophy",
  wellness: "endurance",
};

export const defaultTrainingGoal = (profileGoal: AthleteProfile["goal"] | undefined): TrainingGoal =>
  profileGoal ? BY_PROFILE_GOAL[profileGoal] : "hypertrophy";

/** True when the typed reps (min, and max when given) leave the recommended range. Empty or unparsable input is not judged. */
export function outsideRange(repsMin: string, repsMax: string, range: RepRange): boolean {
  const low = Number.parseInt(repsMin, 10);
  if (!Number.isFinite(low)) return false;
  const parsedMax = Number.parseInt(repsMax, 10);
  const high = Number.isFinite(parsedMax) ? parsedMax : low;
  return low < range.reps_min || high > range.reps_max;
}
