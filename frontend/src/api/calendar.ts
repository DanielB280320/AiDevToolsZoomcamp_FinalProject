import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type Schemas } from "./client";
import { apiError } from "./errors";

export type CalendarDay = Schemas["CalendarDay"];
export type CalendarRange = Schemas["CalendarRange"];
export type DayView = Schemas["DayView"];
export type TrainingStatus = Schemas["TrainingStatus"];

export const dayQueryKey = (athleteId: string, date: string) => ["day", athleteId, date] as const;
export const calendarQueryKey = (athleteId: string, from: string, to: string) =>
  ["calendar", athleteId, from, to] as const;

async function fetchDay(athleteId: string, date: string, signal?: AbortSignal): Promise<DayView> {
  const { data, error, response } = await api.GET("/athletes/{athlete_id}/days/{date}", {
    params: { path: { athlete_id: athleteId, date } },
    signal,
  });
  if (data) return data;
  throw apiError(response, error);
}

/** Today view data. `date` is `today` (resolved by the server in the athlete's zone) or a day. */
export function useDay(athleteId: string, date: string) {
  return useQuery({
    queryKey: dayQueryKey(athleteId, date),
    queryFn: ({ signal }) => fetchDay(athleteId, date, signal),
  });
}

/** Week and Month summaries: one entry per day from `from` to `to` inclusive. */
export function useCalendar(athleteId: string, from: string, to: string) {
  return useQuery({
    queryKey: calendarQueryKey(athleteId, from, to),
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/athletes/{athlete_id}/calendar", {
        params: { path: { athlete_id: athleteId }, query: { from, to } },
        signal,
      });
      if (data) return data;
      throw apiError(response, error);
    },
  });
}

export interface MoveRequest {
  /** Day the session is on now. */
  from: CalendarDay;
  /** Day to move it to (same ISO week). */
  to: string;
}

/**
 * Moves a session within its week. A future planned day has no session row until it is first
 * viewed, so the day is fetched first (the server materialises it idempotently) to get an id.
 */
export function useMoveSession(athleteId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ from, to }: MoveRequest) => {
      const sessionId = from.session_id ?? (await fetchDay(athleteId, from.date)).session?.id;
      if (!sessionId) throw new Error("no session to move");
      const { data, error, response } = await api.POST("/sessions/{session_id}/move", {
        params: { path: { session_id: sessionId } },
        body: { date: to },
      });
      if (data) return data;
      throw apiError(response, error);
    },
    onSettled: () => {
      // Moves change several days and the energy plan of each: refetch every calendar view.
      void queryClient.invalidateQueries({ queryKey: ["calendar", athleteId] });
      void queryClient.invalidateQueries({ queryKey: ["day", athleteId] });
    },
  });
}
