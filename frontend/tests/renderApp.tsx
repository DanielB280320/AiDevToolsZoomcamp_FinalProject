import { QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";

import { createQueryClient } from "../src/queryClient";
import { routes } from "../src/routes";

/**
 * Renders the real route tree at `path` with a fresh copy of the app's query client
 * (same defaults, but no retries and no retry delay; no cache sharing between tests).
 * Returns the router too, so tests can assert where navigation ended up.
 */
export function renderApp(path = "/") {
  const queryClient = createQueryClient();
  const defaults = queryClient.getDefaultOptions();
  queryClient.setDefaultOptions({ ...defaults, queries: { ...defaults.queries, retry: false, retryDelay: 0 } });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const view = render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { ...view, router, queryClient };
}
