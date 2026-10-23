import { http, HttpResponse } from "msw";

import type { components } from "../../src/api/schema";
import { apiUrl } from "./handlers";

type Schemas = components["schemas"];

/** openapi.yaml `MeAthleteNew`, with overrides. */
export function meFixture(overrides: Partial<Schemas["Me"]> = {}): Schemas["Me"] {
  return {
    id: "3f0b6a1e-6a55-4f3c-9a43-1c2a3a4b5c6d",
    email: "ana@example.com",
    display_name: "Ana",
    role: "athlete",
    birth_date: "1995-04-12",
    units: "metric",
    timezone: "Europe/Madrid",
    disclaimer_accepted_at: "2026-10-21T18:00:00Z",
    created_at: "2026-10-21T18:00:00Z",
    onboarding_completed: false,
    active_coach: null,
    pending_coach_link_id: null,
    unread_notification_count: 0,
    ...overrides,
  };
}

/** An RFC 9457 problem response as the backend sends it. */
export function problem(
  status: number,
  code: string,
  extra: Partial<Schemas["Problem"]> = {},
  headers: Record<string, string> = {},
) {
  return HttpResponse.json(
    { type: `/problems/${code}`, title: code, status, code, ...extra } satisfies Schemas["Problem"],
    { status, headers: { "Content-Type": "application/problem+json", ...headers } },
  );
}

export const meOk = (me: Schemas["Me"] = meFixture()) => http.get(apiUrl("/me"), () => HttpResponse.json(me));
export const meUnauthenticated = () =>
  http.get(apiUrl("/me"), () => problem(401, "not_authenticated", { detail: "Sign in to continue." }));
