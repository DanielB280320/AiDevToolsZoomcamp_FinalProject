import type { components } from "../../src/api/schema";

type Schemas = components["schemas"];

/** The recommended rep range per training goal, as the API returns it (D107). */
export const REP_RANGES: Schemas["RepRanges"] = {
  strength: { reps_min: 3, reps_max: 6 },
  hypertrophy: { reps_min: 8, reps_max: 12 },
  endurance: { reps_min: 13, reps_max: 20 },
  maintenance: { reps_min: 6, reps_max: 12 },
  cutting: { reps_min: 8, reps_max: 12 },
};

/** The two `Plan` fields D107 added, for plan fixtures. */
export const PLAN_GOAL = { training_goal: "hypertrophy", rep_ranges: REP_RANGES } as const;
