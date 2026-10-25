import { http, HttpResponse } from "msw";

import type { components } from "../../src/api/schema";
import { defaultCalendar, defaultDay } from "./calendar";

type Schemas = components["schemas"];

/** MSW pattern for an API path on any origin, e.g. apiUrl("/healthz") matches http://localhost:3000/api/v1/healthz. */
export const apiUrl = (path: string) => `*/api/v1${path}`;

/** Default handlers: the happy path for every endpoint the shell calls. Responses follow openapi.yaml. */
export const handlers = [
  http.get(apiUrl("/healthz"), () => HttpResponse.json({ status: "ok", version: "test" } satisfies Schemas["Health"])),
  defaultDay(),
  defaultCalendar(),
];
