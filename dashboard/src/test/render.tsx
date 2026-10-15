import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";

import { routes } from "@/router";

/**
 * `staleTime` defaults to the one the dashboard runs with, so a test sees the cache
 * a person's browser has: an answer read a moment ago is reused, not fetched again.
 */
export function renderAt(path: string, { staleTime = 60_000 }: { staleTime?: number } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime } } });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const view = render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { ...view, router, client };
}
