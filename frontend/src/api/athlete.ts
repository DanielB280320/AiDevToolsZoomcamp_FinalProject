import { useQuery } from "@tanstack/react-query";

import { api, type Schemas } from "./client";
import { apiError } from "./errors";

export type AthleteProfile = Schemas["AthleteProfile"];
export type Targets = Schemas["Targets"];

/** An athlete's profile (`getAthleteProfile`): owner or linked coach. */
export function useAthleteProfile(athleteId: string) {
  return useQuery({
    queryKey: ["athlete-profile", athleteId] as const,
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/athletes/{athlete_id}/profile", {
        params: { path: { athlete_id: athleteId } },
        signal,
      });
      if (data) return data;
      throw apiError(response, error);
    },
  });
}

/** The athlete's current daily targets (`getTargets`): owner or linked coach. */
export function useAthleteTargets(athleteId: string) {
  return useQuery({
    queryKey: ["athlete-targets", athleteId] as const,
    queryFn: async ({ signal }) => {
      const { data, error, response } = await api.GET("/athletes/{athlete_id}/targets", {
        params: { path: { athlete_id: athleteId } },
        signal,
      });
      if (data) return data;
      throw apiError(response, error);
    },
  });
}
