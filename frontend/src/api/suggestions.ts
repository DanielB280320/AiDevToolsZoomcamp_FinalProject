import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type Schemas } from "./client";
import { apiError } from "./errors";

export type Suggestion = Schemas["Suggestion"];
export type ProgressionSuggestion = Schemas["ProgressionSuggestion"];
export type ExerciseTargets = Schemas["ExerciseTargets"];
export type AcceptOverrides = NonNullable<Schemas["AcceptSuggestionRequest"]["overrides"]>;

export const pendingSuggestionsKey = (athleteId: string) => ["suggestions", athleteId, "pending"] as const;

/** Pending suggestions, newest first (`listSuggestions`, F11). */
export function usePendingSuggestions(athleteId: string) {
  return useQuery({
    queryKey: pendingSuggestionsKey(athleteId),
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/athletes/{athlete_id}/suggestions", {
        params: { path: { athlete_id: athleteId }, query: { status: "pending" } },
        signal,
      });
      if (data) return data.items;
      throw apiError(response, error);
    },
  });
}

/** Deciding changes the pending list and, on accept, the targets on Today, the session and the plan. */
function useRefreshAfterDecision() {
  const queryClient = useQueryClient();
  return () => {
    for (const key of ["suggestions", "day", "session", "calendar"]) {
      void queryClient.invalidateQueries({ queryKey: [key] });
    }
  };
}

/** Accept as proposed, or edit-then-accept when `overrides` is given. */
export function useAcceptSuggestion() {
  const refresh = useRefreshAfterDecision();
  return useMutation({
    mutationFn: async ({ id, overrides }: { id: string; overrides?: AcceptOverrides }) => {
      const { data, error, response } = await api.POST("/suggestions/{suggestion_id}/accept", {
        params: { path: { suggestion_id: id } },
        body: overrides ? { overrides } : undefined,
      });
      if (data) return data;
      throw apiError(response, error);
    },
    // Also after a 409: the list must show what was decided elsewhere.
    onSettled: refresh,
  });
}

export function useRejectSuggestion() {
  const refresh = useRefreshAfterDecision();
  return useMutation({
    mutationFn: async (id: string) => {
      const { data, error, response } = await api.POST("/suggestions/{suggestion_id}/reject", {
        params: { path: { suggestion_id: id } },
      });
      if (data) return data;
      throw apiError(response, error);
    },
    onSettled: refresh,
  });
}
