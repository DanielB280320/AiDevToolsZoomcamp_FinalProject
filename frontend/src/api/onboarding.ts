import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type Schemas } from "./client";
import { apiError } from "./errors";
import { meQueryKey } from "./session";

export type OnboardingRequest = Schemas["OnboardingRequest"];
export type OnboardingResult = Schemas["OnboardingResult"];
export type AthleteProfileInput = Schemas["AthleteProfileInput"];
export type OnboardingBodyMetric = Schemas["OnboardingBodyMetric"];
export type Exercise = Schemas["Exercise"];

export async function completeOnboarding(athleteId: string, body: OnboardingRequest): Promise<OnboardingResult> {
  const { data, error, response } = await api.POST("/athletes/{athlete_id}/onboarding", {
    params: { path: { athlete_id: athleteId } },
    body,
  });
  if (data) return data;
  throw apiError(response, error);
}

/** `POST /athletes/{id}/onboarding`. The result is kept for the review step; `GET /me` is refreshed. */
export function useCompleteOnboarding(athleteId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: OnboardingRequest) => completeOnboarding(athleteId, body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: meQueryKey }),
  });
}

/** Exercise catalog search by name (F4.2), for the "exercises to avoid" picker. */
export function useExerciseSearch(text: string) {
  const q = text.trim();
  return useQuery({
    queryKey: ["exercises", "search", q],
    enabled: q.length >= 2,
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/exercises", { params: { query: { q, limit: 20 } }, signal });
      if (data) return data.items;
      throw apiError(response, error);
    },
  });
}
