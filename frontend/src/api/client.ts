import createClient, { type ClientOptions } from "openapi-fetch";

import type { components, paths } from "./schema";

/** Every API path is relative to this base (openapi.yaml `servers`, ADR 0005). */
export const API_BASE_URL = "/api/v1";

/**
 * Creates a typed client for the FitWise API. Request and response types come
 * only from the generated `schema.d.ts`; never hand-write payload types.
 *
 * The session is an HttpOnly cookie, so every request sends credentials.
 */
export function createApiClient(options: Omit<ClientOptions, "baseUrl" | "credentials"> = {}) {
  return createClient<paths>({
    // Look fetch up per request (not once at import) so wrappers installed later,
    // such as instrumentation or the test mock server, are honoured.
    fetch: (request: Request) => globalThis.fetch(request),
    ...options,
    baseUrl: API_BASE_URL,
    credentials: "include",
  });
}

export const api = createApiClient();

export type ApiClient = ReturnType<typeof createApiClient>;
export type Schemas = components["schemas"];
