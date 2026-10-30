import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type Schemas } from "./client";
import { apiError } from "./errors";

export type MealLog = Schemas["MealLog"];
export type MealLogInput = Schemas["MealLogInput"];
export type Food = Schemas["Food"];
export type FoodInput = Schemas["FoodInput"];
export type OffProduct = Schemas["OffProduct"];
export type MealSlot = Schemas["MealSlot"];

/** A meal log changes the day (eaten totals, completion) and the calendar's meal counts. */
function useRefreshDay() {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: ["day"] });
    void queryClient.invalidateQueries({ queryKey: ["calendar"] });
  };
}

/** Check off, adjust, skip or add a meal. Idempotent per (date, planned meal): a repeat is safe. */
export function useLogMeal(athleteId: string) {
  const refresh = useRefreshDay();
  return useMutation({
    mutationFn: async (input: MealLogInput) => {
      const { data, error, response } = await api.POST("/athletes/{athlete_id}/meal-logs", {
        params: { path: { athlete_id: athleteId } },
        body: input,
      });
      if (data) return data;
      throw apiError(response, error);
    },
    onSettled: refresh,
  });
}

export function useDeleteMealLog(athleteId: string) {
  const refresh = useRefreshDay();
  return useMutation({
    mutationFn: async (mealLogId: string) => {
      const { data, error, response } = await api.DELETE("/athletes/{athlete_id}/meal-logs/{meal_log_id}", {
        params: { path: { athlete_id: athleteId, meal_log_id: mealLogId } },
      });
      if (data) return data;
      throw apiError(response, error);
    },
    onSettled: refresh,
  });
}

/** Local food library search (seed, imported and the user's custom foods). */
export function useFoodSearch(text: string) {
  const q = text.trim();
  return useQuery({
    queryKey: ["foods", "search", q],
    enabled: q.length >= 2,
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/foods", { params: { query: { q, limit: 10 } }, signal });
      if (data) return data.items;
      throw apiError(response, error);
    },
  });
}

/** Open Food Facts search; runs only for an explicit request (`q` set by the "search online" button). */
export function useOffSearch(q: string) {
  return useQuery({
    queryKey: ["foods", "off", q],
    enabled: q.length >= 2,
    staleTime: 60_000,
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/foods/search", { params: { query: { q } }, signal });
      if (data) return data;
      throw apiError(response, error);
    },
  });
}

/** Copies an Open Food Facts product into the library; importing twice returns the same food. */
export function useImportOffFood() {
  return useMutation({
    mutationFn: async (code: string) => {
      const { data, error, response } = await api.POST("/foods/import", { body: { code } });
      if (data) return data;
      throw apiError(response, error);
    },
  });
}

export function useCreateFood() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: FoodInput) => {
      const { data, error, response } = await api.POST("/foods", { body: input });
      if (data) return data;
      throw apiError(response, error);
    },
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["foods"] }),
  });
}
