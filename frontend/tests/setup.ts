import "@testing-library/jest-dom/vitest";
import "../src/i18n";

import { cleanup, configure } from "@testing-library/react";
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

// Recharts' ResponsiveContainer sizes itself from a ResizeObserver; jsdom has no layout and no
// ResizeObserver. This stub reports a fixed 320 x 240 box so charts render their markup.
if (typeof window !== "undefined" && !("ResizeObserver" in window)) {
  class FixedResizeObserver {
    constructor(private readonly callback: ResizeObserverCallback) {}
    observe(target: Element) {
      const rect = { width: 320, height: 240, top: 0, left: 0, right: 320, bottom: 240, x: 0, y: 0 } as DOMRectReadOnly;
      const entry = { target, contentRect: rect, borderBoxSize: [], contentBoxSize: [], devicePixelContentBoxSize: [] };
      queueMicrotask(() => this.callback([entry as ResizeObserverEntry], this as unknown as ResizeObserver));
    }
    unobserve() {}
    disconnect() {}
  }
  globalThis.ResizeObserver = FixedResizeObserver;
}

// findBy*/waitFor budget: the 1 s default is too tight for page transitions on a loaded host.
configure({ asyncUtilTimeout: 5_000 });

// No real network in tests (CLAUDE.md rule 4): any request without a handler fails the test.
beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterEach(() => {
  cleanup();
  server.resetHandlers();
});
afterAll(() => server.close());
