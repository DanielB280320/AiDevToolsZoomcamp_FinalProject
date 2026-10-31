import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type Schemas } from "./client";
import { apiError, isApiError } from "./errors";

export type Plan = Schemas["Plan"];
export type TrainingDay = Schemas["TrainingDay"];
export type PlannedExercise = Schemas["PlannedExercise"];
export type MealDay = Schemas["MealDay"];
export type PlannedMeal = Schemas["PlannedMeal"];
export type TrainingPlanUpdate = Schemas["TrainingPlanUpdate"];
export type MealPlanUpdate = Schemas["MealPlanUpdate"];
export type PlanVersionSummary = Schemas["PlanVersionSummary"];
export type Weekday = Schemas["Weekday"];
export type Meal = Schemas["Meal"];
export type MealInput = Schemas["MealInput"];
export type RegeneratePlanRequest = Schemas["RegeneratePlanRequest"];
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

export function usePlanVersions(athleteId: string) {
  return useQuery({
    queryKey: ["plan-versions", athleteId],
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/athletes/{athlete_id}/plan/versions", {
        params: { path: { athlete_id: athleteId } },
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
