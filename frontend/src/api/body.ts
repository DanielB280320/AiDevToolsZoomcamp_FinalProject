import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type Schemas } from "./client";
import { apiError } from "./errors";

export type BodyMetric = Schemas["BodyMetric"];
export type BodyMetricInput = Schemas["BodyMetricInput"];
export type RecalcSuggestion = Extract<Schemas["Suggestion"], { kind: "recalc" }>;

export const bodyMetricsKey = (athleteId: string) => ["body-metrics", athleteId] as const;

/** Entries of the last 90 days, oldest first (`listBodyMetrics`). */
export function useBodyMetrics(athleteId: string, enabled = true) {
  return useQuery({
    queryKey: bodyMetricsKey(athleteId),
    enabled,
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/athletes/{athlete_id}/body-metrics", {
        params: { path: { athlete_id: athleteId } },
        signal,
      });
      if (data) return data.items;
      throw apiError(response, error);
    },
  });
}

export interface WeighInOutcome {
  metric: BodyMetric;
  /** `200`: an entry for that day already existed and was replaced; `201`: a new entry. */
  replaced: boolean;
  recalc: RecalcSuggestion | null;
}

/** Logs a weigh-in (`logBodyMetric`). The API receives metric values only. */
export function useLogBodyMetric(athleteId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: BodyMetricInput): Promise<WeighInOutcome> => {
      const { data, error, response } = await api.POST("/athletes/{athlete_id}/body-metrics", {
        params: { path: { athlete_id: athleteId } },
        body: input,
      });
      if (!data) throw apiError(response, error);
      const recalc = data.recalc_suggestion;
      return {
        metric: data.body_metric,
        replaced: response.status === 200,
        recalc: recalc && recalc.kind === "recalc" ? recalc : null,
      };
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: bodyMetricsKey(athleteId) });
      void queryClient.invalidateQueries({ queryKey: ["suggestions"] });
    },
  });
}
