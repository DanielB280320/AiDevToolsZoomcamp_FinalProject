import { useQuery } from "@tanstack/react-query";

import { api, type Schemas } from "./client";
import { apiError } from "./errors";

export type SessionChart = Schemas["SessionChart"];
export type SessionChartExercise = Schemas["SessionChartExercise"];
export type SessionChartSet = Schemas["SessionChartSet"];
export type SetStatus = Schemas["SetStatus"];
export type ExerciseChart = Schemas["ExerciseChart"];
export type ExerciseChartPoint = Schemas["ExerciseChartPoint"];
export type AdherenceChart = Schemas["AdherenceChart"];
export type AdherenceDay = Schemas["AdherenceDay"];
export type AdherenceWeek = Schemas["AdherenceWeek"];
export type WeeklySummary = Schemas["WeeklySummary"];
export type BodyChart = Schemas["BodyChart"];
export type BodyChartPoint = Schemas["BodyChartPoint"];
export type DatedValueSeries = WeeklySummary["sparklines"]["weight_avg_kg"];

/** The only range lengths the chart endpoints accept (D76(4)). */
export const CHART_WEEKS = [4, 12, 26, 52] as const;
export type ChartWeeks = (typeof CHART_WEEKS)[number];
export const DEFAULT_CHART_WEEKS: ChartWeeks = 12;

export const chartsKey = (athleteId: string, ...rest: unknown[]) => ["charts", athleteId, ...rest] as const;

/** Per-set target vs. actual of one session (`getSessionChart`). */
export function useSessionChart(athleteId: string, sessionId: string) {
  return useQuery({
    queryKey: chartsKey(athleteId, "session", sessionId),
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/athletes/{athlete_id}/charts/session/{session_id}", {
        params: { path: { athlete_id: athleteId, session_id: sessionId } },
        signal,
      });
      if (data) return data;
      throw apiError(response, error);
    },
  });
}

/** One exercise over the last `weeks` weeks (`getExerciseChart`). */
export function useExerciseChart(athleteId: string, exerciseId: string | null, weeks: ChartWeeks) {
  return useQuery({
    queryKey: chartsKey(athleteId, "exercise", exerciseId, weeks),
    enabled: exerciseId !== null,
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/athletes/{athlete_id}/charts/exercise/{exercise_id}", {
        params: { path: { athlete_id: athleteId, exercise_id: exerciseId ?? "" }, query: { weeks } },
        signal,
      });
      if (data) return data;
      throw apiError(response, error);
    },
  });
}

/** Daily and weekly completion for `from`..`to` (`getAdherenceChart`). */
export function useAdherenceChart(athleteId: string, from: string, to: string) {
  return useQuery({
    queryKey: chartsKey(athleteId, "adherence", from, to),
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/athletes/{athlete_id}/charts/adherence", {
        params: { path: { athlete_id: athleteId }, query: { from, to } },
        signal,
      });
      if (data) return data;
      throw apiError(response, error);
    },
  });
}

/** Tiles and sparklines of the week starting `weekStart` (a Monday), or the current week. */
export function useWeeklySummary(athleteId: string, weekStart: string | null) {
  return useQuery({
    queryKey: chartsKey(athleteId, "weekly-summary", weekStart),
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/athletes/{athlete_id}/charts/weekly-summary", {
        params: { path: { athlete_id: athleteId }, query: weekStart ? { week_start: weekStart } : {} },
        signal,
      });
      if (data) return data;
      throw apiError(response, error);
    },
  });
}

/** Weight, 7-day average and body fat over the last `weeks` weeks (`getBodyChart`). */
export function useBodyChart(athleteId: string, weeks: ChartWeeks) {
  return useQuery({
    queryKey: chartsKey(athleteId, "body", weeks),
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/athletes/{athlete_id}/charts/body", {
        params: { path: { athlete_id: athleteId }, query: { weeks } },
        signal,
      });
      if (data) return data;
      throw apiError(response, error);
    },
  });
}
