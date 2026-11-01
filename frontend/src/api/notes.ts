import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api, type Schemas } from "./client";
import { apiError } from "./errors";

export type CoachNote = Schemas["Note"];
export type NoteInput = Schemas["NoteInput"];

/** Notes show inside the day view, so every change refreshes the athlete's days. */
function useRefreshDays(athleteId: string) {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: ["day", athleteId] });
  };
}

/** `createNote`: only a linked coach (F16); the athlete is notified by the server. */
export function useCreateNote(athleteId: string) {
  const refresh = useRefreshDays(athleteId);
  return useMutation({
    mutationFn: async (body: NoteInput) => {
      const { data, error, response } = await api.POST("/athletes/{athlete_id}/notes", {
        params: { path: { athlete_id: athleteId } },
        body,
      });
      if (data) return data;
      throw apiError(response, error);
    },
    onSuccess: refresh,
  });
}

/** `updateNote`: author only. */
export function useUpdateNote(athleteId: string) {
  const refresh = useRefreshDays(athleteId);
  return useMutation({
    mutationFn: async ({ id, text }: { id: string; text: string }) => {
      const { data, error, response } = await api.PUT("/athletes/{athlete_id}/notes/{note_id}", {
        params: { path: { athlete_id: athleteId, note_id: id } },
        body: { text },
      });
      if (data) return data;
      throw apiError(response, error);
    },
    onSuccess: refresh,
  });
}

/** `deleteNote`: author only. */
export function useDeleteNote(athleteId: string) {
  const refresh = useRefreshDays(athleteId);
  return useMutation({
    mutationFn: async (id: string) => {
      const { error, response } = await api.DELETE("/athletes/{athlete_id}/notes/{note_id}", {
        params: { path: { athlete_id: athleteId, note_id: id } },
      });
      if (!response.ok) throw apiError(response, error);
    },
    onSuccess: refresh,
  });
}
