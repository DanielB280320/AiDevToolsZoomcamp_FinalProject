import { type QueryClient, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type Schemas } from "./client";
import { apiError, isApiError } from "./errors";

export type Me = Schemas["Me"];
export type SignUpRequest = Schemas["SignUpRequest"];
export type LogInRequest = Schemas["LogInRequest"];

/** Query key of the signed-in user (`GET /me`). */
export const meQueryKey = ["me"] as const;

export async function fetchMe(signal?: AbortSignal): Promise<Me> {
  const { data, error, response } = await api.GET("/me", { signal });
  if (data) return data;
  throw apiError(response, error);
}

export function isUnauthenticated(error: unknown): boolean {
  return isApiError(error) && error.status === 401;
}

/** The signed-in user. A 401 is final (no retry): the caller redirects to sign-in. */
export function useMe() {
  return useQuery({
    queryKey: meQueryKey,
    queryFn: ({ signal }) => fetchMe(signal),
    retry: (failureCount, error) => !isUnauthenticated(error) && failureCount < 2,
  });
}

/** The cached user, if a page already loaded it. Never sends a request. */
export function useCachedMe(): Me | undefined {
  const { data } = useQuery({ queryKey: meQueryKey, queryFn: () => fetchMe(), enabled: false });
  return data;
}

export async function signUp(body: SignUpRequest): Promise<Me> {
  const { data, error, response } = await api.POST("/auth/signup", { body });
  if (data) return data;
  throw apiError(response, error);
}

export async function logIn(body: LogInRequest): Promise<Me> {
  const { data, error, response } = await api.POST("/auth/login", { body });
  if (data) return data;
  throw apiError(response, error);
}

/**
 * Drops every cached query except the `me` entry itself. The `me` query is reset or overwritten
 * in place instead of removed: components that read it (the header) keep observing the same cache
 * entry, so they see the change. Removing it would leave them showing the old user.
 */
export function dropUserDataExceptMe(queryClient: QueryClient) {
  queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== meQueryKey[0] });
}

/** Sign-up and sign-in share this: on success the new session's user is cached for /today. */
export function useStartSession<T>(request: (body: T) => Promise<Me>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: request,
    onSuccess: (me) => {
      // A previous user's data must never survive into this session.
      dropUserDataExceptMe(queryClient);
      queryClient.setQueryData(meQueryKey, me);
    },
  });
}

/**
 * `POST /auth/logout`, then `leave()` (navigate to sign-in), then drop every cached query (user data).
 * Clearing only after leaving keeps the signed-in page from refetching `GET /me` on its way out.
 */
export function useSignOut(leave: () => Promise<void> | void) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { response, error } = await api.POST("/auth/logout");
      if (!response.ok) throw apiError(response, error);
    },
    onSuccess: async () => {
      await leave();
      dropUserDataExceptMe(queryClient);
      // Back to "no data": the header hides sign-out; nothing on the sign-in page refetches it.
      await queryClient.resetQueries({ queryKey: meQueryKey });
    },
  });
}
