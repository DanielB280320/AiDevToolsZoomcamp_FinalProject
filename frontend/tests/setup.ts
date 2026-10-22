import "@testing-library/jest-dom/vitest";
import "../src/i18n";

import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll } from "vitest";

import { server } from "./mocks/server";

// Browsers resolve relative request URLs against the page; Node's Request does not.
// Emulate the browser so the client keeps its real base URL ("/api/v1") under test.
// Only in DOM tests; node-environment tests (eslint, generator) have no window.
if (typeof window !== "undefined") {
  const NodeRequest = globalThis.Request;
  class BrowserLikeRequest extends NodeRequest {
    constructor(input: RequestInfo | URL, init?: RequestInit) {
      super(typeof input === "string" ? new URL(input, window.location.href) : input, init);
    }
  }
  globalThis.Request = BrowserLikeRequest;
}

// No real network in tests (CLAUDE.md rule 4): any request without a handler fails the test.
beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterEach(() => {
  cleanup();
  server.resetHandlers();
});
afterAll(() => server.close());
