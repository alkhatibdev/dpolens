import "@fontsource/readex-pro/300.css";
import "@fontsource/readex-pro/400.css";
import "@fontsource/readex-pro/500.css";
import "@fontsource/readex-pro/600.css";
import "@fontsource/readex-pro/700.css";
import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/500.css";
import "./index.css";
import "./i18n";

import { QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router/dom";

import { ApiError } from "./api/client";
import { router } from "./router";
import { SESSION } from "./session";

const client: QueryClient = new QueryClient({
  queryCache: new QueryCache({
    // A session that ends while a page is open sends the next call back a 401.
    // Resetting the session, rather than refreshing it, drops the answer cached
    // from before, so nothing goes on believing the person is still signed in.
    onError: (error, query) => {
      if (error instanceof ApiError && error.status === 401 && query.queryKey[0] !== SESSION[0]) {
        void client.resetQueries({ queryKey: SESSION });
      }
    },
  }),
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      retry: (failures, error) =>
        !(error instanceof ApiError && error.status < 500) && failures < 2,
    },
  },
});

const root = document.getElementById("root");
if (root) {
  createRoot(root).render(
    <StrictMode>
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </StrictMode>,
  );
}
