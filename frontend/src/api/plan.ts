import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type Schemas } from "./client";
import { apiError, isApiError } from "./errors";

export type Plan = Schemas["Plan"];
export type TrainingDay = Schemas["TrainingDay"];
export type PlannedExercise = Schemas["PlannedExercise"];
export type MealDay = Schemas["MealDay"];
export type PlannedMeal = Schemas["PlannedMeal"];
export type MealSwap = Schemas["MealSwap"];
export type TrainingPlanUpdate = Schemas["TrainingPlanUpdate"];
export type MealPlanUpdate = Schemas["MealPlanUpdate"];
export type PlanVersionSummary = Schemas["PlanVersionSummary"];
export type PlanSummary = Schemas["PlanSummary"];
export type PlanChangeSummary = Schemas["PlanChangeSummary"];
export type Weekday = Schemas["Weekday"];
export type Meal = Schemas["Meal"];
export type MealInput = Schemas["MealInput"];
export type RegeneratePlanRequest = Schemas["RegeneratePlanRequest"];
export type CreatePlanRequest = Schemas["CreatePlanRequest"];
export type ProgressionRule = Schemas["ProgressionRule"];

export const WEEKDAYS: readonly Weekday[] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];

export const planKey = (athleteId: string) => ["plan", athleteId] as const;

/** The active plan version (`revision` is sent back with every edit). */
export function usePlan(athleteId: string) {
  return useQuery({
    queryKey: planKey(athleteId),
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/athletes/{athlete_id}/plan", {
        params: { path: { athlete_id: athleteId } },
        signal,
      });
      if (data) return data;
      throw apiError(response, error);
    },
  });
}

/** One item per plan, newest first (D106). */
export function usePlans(athleteId: string) {
  return useQuery({
    queryKey: ["plan-versions", athleteId, "plans"],
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/athletes/{athlete_id}/plans", {
        params: { path: { athlete_id: athleteId } },
        signal,
      });
      if (data) return data.items;
      throw apiError(response, error);
    },
  });
}

/** The versions of one plan, newest first: its change timeline (D106). */
export function usePlanVersions(athleteId: string, planNo: number | null) {
  return useQuery({
    queryKey: ["plan-versions", athleteId, "plan", planNo],
    enabled: planNo !== null,
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/athletes/{athlete_id}/plan/versions", {
        params: { path: { athlete_id: athleteId }, query: { plan_no: planNo! } },
        signal,
      });
      if (data) return data.items;
      throw apiError(response, error);
    },
  });
}

export function usePlanVersion(athleteId: string, version: number | null) {
  return useQuery({
    queryKey: ["plan-version", athleteId, version],
    enabled: version !== null,
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/athletes/{athlete_id}/plan/versions/{version}", {
        params: { path: { athlete_id: athleteId, version: version! } },
        signal,
      });
      if (data) return data;
      throw apiError(response, error);
    },
  });
}

/** A new plan version changes the day views, the calendar and the version list. */
function useAfterPlanChange(athleteId: string) {
  const queryClient = useQueryClient();
  return (plan: Plan) => {
    queryClient.setQueryData(planKey(athleteId), plan);
    void queryClient.invalidateQueries({ queryKey: ["plan-versions", athleteId] });
    void queryClient.invalidateQueries({ queryKey: ["day"] });
    void queryClient.invalidateQueries({ queryKey: ["calendar"] });
  };
}

/** On a stale `revision` (409) the plan is refetched; the caller keeps the user's draft. */
function useRefetchOnConflict(athleteId: string) {
  const queryClient = useQueryClient();
  return (error: unknown) => {
    if (isApiError(error) && error.status === 409) {
      void queryClient.invalidateQueries({ queryKey: planKey(athleteId) });
    }
  };
}

export function useSaveTraining(athleteId: string) {
  const after = useAfterPlanChange(athleteId);
  const onConflict = useRefetchOnConflict(athleteId);
  return useMutation({
    mutationFn: async (body: TrainingPlanUpdate) => {
      const { data, error, response } = await api.PUT("/athletes/{athlete_id}/plan/training", {
        params: { path: { athlete_id: athleteId } },
        body,
      });
      if (data) return data;
      throw apiError(response, error);
    },
    onSuccess: after,
    onError: onConflict,
  });
}

export function useSaveMeals(athleteId: string) {
  const after = useAfterPlanChange(athleteId);
  const onConflict = useRefetchOnConflict(athleteId);
  return useMutation({
    mutationFn: async (body: MealPlanUpdate) => {
      const { data, error, response } = await api.PUT("/athletes/{athlete_id}/plan/meals", {
        params: { path: { athlete_id: athleteId } },
        body,
      });
      if (data) return data;
      throw apiError(response, error);
    },
    onSuccess: after,
    onError: onConflict,
  });
}

export function useRegeneratePlan(athleteId: string) {
  const after = useAfterPlanChange(athleteId);
  return useMutation({
    mutationFn: async (body: RegeneratePlanRequest = { scope: "all" }) => {
      const { data, error, response } = await api.POST("/athletes/{athlete_id}/plan/regenerate", {
        params: { path: { athlete_id: athleteId } },
        body,
      });
      if (data) return data;
      throw apiError(response, error);
    },
    onSuccess: after,
  });
}

/** A new named plan, empty or generated; it replaces the active one at once (D105). */
export function useCreatePlan(athleteId: string) {
  const after = useAfterPlanChange(athleteId);
  return useMutation({
    mutationFn: async (body: CreatePlanRequest) => {
      const { data, error, response } = await api.POST("/athletes/{athlete_id}/plan", {
        params: { path: { athlete_id: athleteId } },
        body,
      });
      if (data) return data;
      throw apiError(response, error);
    },
    onSuccess: after,
  });
}

/** Make a previous plan the current one; no version is written (D108). */
export function useActivatePlan(athleteId: string) {
  const after = useAfterPlanChange(athleteId);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (planNo: number) => {
      const { data, error, response } = await api.POST("/athletes/{athlete_id}/plans/{plan_no}/activate", {
        params: { path: { athlete_id: athleteId, plan_no: planNo } },
      });
      if (data) return data;
      throw apiError(response, error);
    },
    onSuccess: (plan: Plan) => {
      after(plan);
      // The server rejects the pending suggestions of the plan that was current.
      void queryClient.invalidateQueries({ queryKey: ["suggestions"] });
    },
  });
}

/** Delete a plan that is not the current one (D108). */
export function useDeletePlan(athleteId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (planNo: number) => {
      const { error, response } = await api.DELETE("/athletes/{athlete_id}/plans/{plan_no}", {
        params: { path: { athlete_id: athleteId, plan_no: planNo } },
      });
      if (response.ok) return;
      throw apiError(response, error);
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["plan-versions", athleteId] }),
  });
}

/** Meal library search for the meal picker, optionally for one slot. */
export function useMealSearch(text: string, slot: Schemas["MealSlot"] | undefined) {
  const q = text.trim();
  return useQuery({
    queryKey: ["meals", "search", q, slot ?? null],
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/meals", {
        params: { query: { q: q || undefined, slot, limit: 10 } },
        signal,
      });
      if (data) return data.items;
      throw apiError(response, error);
    },
  });
}

export function useCreateMeal() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: MealInput) => {
      const { data, error, response } = await api.POST("/meals", { body: input });
      if (data) return data;
      throw apiError(response, error);
    },
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["meals"] }),
  });
}

/** Alternatives with similar kcal for a planned meal of the saved plan (D86); read-only. */
export function useMealSwaps(athleteId: string, mealKey: string, enabled: boolean) {
  return useQuery({
    queryKey: ["meal-swaps", athleteId, mealKey],
    enabled,
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/athletes/{athlete_id}/plan/meals/{meal_key}/swaps", {
        params: { path: { athlete_id: athleteId, meal_key: mealKey } },
        signal,
      });
      if (data) return data;
      throw apiError(response, error);
    },
  });
}
