import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type Schemas } from "./client";
import { apiError } from "./errors";
import { meQueryKey } from "./session";

export type CoachProfile = Schemas["CoachProfile"];
export type CoachProfileInput = Schemas["CoachProfileInput"];
export type CoachSearchResult = Schemas["CoachSearchResult"];
export type CoachLink = Schemas["CoachLink"];
export type CoachLinkStatus = Schemas["CoachLinkStatus"];

export type CoachAthleteSummary = Schemas["CoachAthleteSummary"];
export type AttentionReason = Schemas["AttentionReason"];

export const coachAthletesKey = ["coach-athletes"] as const;

/** The coach's clients in the order the API returns them: needs attention first (`listCoachAthletes`, F16.5). */
export function useCoachAthletes(enabled = true, refetchInterval: number | false = false) {
  return useQuery({
    queryKey: coachAthletesKey,
    enabled,
    refetchInterval,
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/coach/athletes", { signal });
      if (data) return data.items;
      throw apiError(response, error);
    },
  });
}

export const coachProfileKey = ["coach-profile"] as const;
export const coachLinksKey = ["coach-links"] as const;

/** My coach profile (`getCoachProfile`, coaches only). */
export function useCoachProfile() {
  return useQuery({
    queryKey: coachProfileKey,
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/coach/profile", { signal });
      if (data) return data;
      throw apiError(response, error);
    },
  });
}

export function useUpdateCoachProfile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: CoachProfileInput) => {
      const { data, error, response } = await api.PUT("/coach/profile", { body });
      if (data) return data;
      throw apiError(response, error);
    },
    onSuccess: (data) => queryClient.setQueryData(coachProfileKey, data),
  });
}

/** Discoverable coaches by name or exact email (`searchCoaches`); runs only for `q` of 3+ characters. */
export function useCoachSearch(q: string) {
  return useQuery({
    queryKey: ["coach-search", q] as const,
    enabled: q.length >= 3,
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/coaches/search", { params: { query: { q } }, signal });
      if (data) return data.items;
      throw apiError(response, error);
    },
  });
}

/** My links, newest first (`listCoachLinks`): an athlete's own, or a coach's links with athletes. */
export function useCoachLinks() {
  return useQuery({
    queryKey: coachLinksKey,
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/coach-links", { signal });
      if (data) return data.items;
      throw apiError(response, error);
    },
  });
}

/** Any link change also changes `Me.active_coach` / `pending_coach_link_id`; refetch after errors too. */
function useRefreshLinks() {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: coachLinksKey });
    void queryClient.invalidateQueries({ queryKey: meQueryKey });
    void queryClient.invalidateQueries({ queryKey: coachAthletesKey });
  };
}

export function useRequestCoachLink() {
  const refresh = useRefreshLinks();
  return useMutation({
    mutationFn: async (coachId: string) => {
      const { data, error, response } = await api.POST("/coach-links", { body: { coach_id: coachId } });
      if (data) return data;
      throw apiError(response, error);
    },
    onSettled: refresh,
  });
}

export type LinkAction = "approve" | "decline" | "end";

export function useCoachLinkAction() {
  const refresh = useRefreshLinks();
  return useMutation({
    mutationFn: async ({ id, action }: { id: string; action: LinkAction }) => {
      const path = `/coach-links/{link_id}/${action}` as const;
      const { data, error, response } = await api.POST(path, { params: { path: { link_id: id } } });
      if (data) return data;
      throw apiError(response, error);
    },
    onSettled: refresh,
  });
}
