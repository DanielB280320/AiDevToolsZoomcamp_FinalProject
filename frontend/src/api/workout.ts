import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { api, type Schemas } from "./client";
import { apiError } from "./errors";

export type Session = Schemas["Session"];
export type SessionExercise = Schemas["SessionExercise"];
export type SessionSet = Schemas["SessionSet"];
export type SetLog = Schemas["SetLog"];
export type SetLogInput = Schemas["SetLogInput"];
export type FinishSessionResult = Schemas["FinishSessionResult"];
export type Suggestion = Schemas["Suggestion"];
export type ExerciseSummary = Schemas["ExerciseSummary"];

export const sessionQueryKey = (sessionId: string) => ["session", sessionId] as const;

/** One session with its planned sets and logs (`getSession`). */
export function useSession(sessionId: string) {
  return useQuery({
    queryKey: sessionQueryKey(sessionId),
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/sessions/{session_id}", {
        params: { path: { session_id: sessionId } },
        signal,
      });
      if (data) return data;
      throw apiError(response, error);
    },
  });
}

/** Logging changes the session, the day's energy balance and the calendar badges. */
function invalidateAfterLogging(queryClient: QueryClient, sessionId: string) {
  void queryClient.invalidateQueries({ queryKey: sessionQueryKey(sessionId) });
  void queryClient.invalidateQueries({ queryKey: ["day"] });
  void queryClient.invalidateQueries({ queryKey: ["calendar"] });
  void queryClient.invalidateQueries({ queryKey: ["suggestions"] });
}

/** Idempotent per (session, exercise, set number): retrying the same input never duplicates a set. */
export function useLogSet(sessionId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: SetLogInput) => {
      const { data, error, response } = await api.POST("/sessions/{session_id}/sets", {
        params: { path: { session_id: sessionId } },
        body: input,
      });
      if (data) return data;
      throw apiError(response, error);
    },
    onSettled: () => invalidateAfterLogging(queryClient, sessionId),
  });
}

/** Closes the workout; allowed again inside the edit window to recompute completion. */
export function useFinishSession(sessionId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.POST("/sessions/{session_id}/finish", {
        params: { path: { session_id: sessionId } },
        body: {},
      });
      if (data) return data;
      throw apiError(response, error);
    },
    onSettled: () => invalidateAfterLogging(queryClient, sessionId),
  });
}
