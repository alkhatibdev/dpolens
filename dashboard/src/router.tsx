import { createBrowserRouter, Outlet } from "react-router";

import { PageFailed, StartFailed, Starting } from "@/components/States";
import { Shell } from "@/layout/Shell";
import { Home } from "@/pages/Home";
import { NotFoundPage } from "@/pages/NotFound";
import { RequireSession } from "@/RequireSession";

// Each page is a file of its own in the build, fetched the first time somebody
// opens it, so the dashboard starts without loading every page it has. Each
// `lazy` is a function: written as an object, the tests' routers answered "No
// route matches" for a page's first visit.
export const routes = [
  {
    path: "/sign-in",
    HydrateFallback: Starting,
    ErrorBoundary: StartFailed,
    lazy: async () => ({ Component: (await import("@/pages/SignIn")).SignInPage }),
  },
  {
    path: "/welcome",
    HydrateFallback: Starting,
    ErrorBoundary: StartFailed,
    lazy: async () => ({ Component: (await import("@/pages/Welcome")).WelcomePage }),
  },
  {
    path: "/setup",
    HydrateFallback: Starting,
    ErrorBoundary: StartFailed,
    element: (
      <RequireSession>
        <Outlet />
      </RequireSession>
    ),
    children: [
      {
        index: true,
        lazy: async () => ({ Component: (await import("@/pages/Setup")).SetupPage }),
      },
    ],
  },
  {
    path: "/",
    HydrateFallback: Starting,
    ErrorBoundary: StartFailed,
    element: (
      <RequireSession>
        <Shell />
      </RequireSession>
    ),
    children: [
      {
        // A page that fails says so inside the frame, so the menu stays.
        ErrorBoundary: PageFailed,
        children: [
          { index: true, element: <Home /> },
          {
            path: "overview",
            lazy: async () => ({ Component: (await import("@/pages/Overview")).OverviewPage }),
          },
          {
            path: "logs",
            lazy: async () => ({ Component: (await import("@/pages/Questions")).QuestionsPage }),
          },
          {
            path: "logs/governance",
            lazy: async () => ({
              Component: (await import("@/pages/Governance")).GovernancePage,
            }),
          },
          {
            path: "library",
            lazy: async () => ({ Component: (await import("@/pages/Library")).LibraryPage }),
          },
          {
            path: "library/:slug",
            lazy: async () => ({ Component: (await import("@/pages/Document")).DocumentPage }),
          },
          {
            path: "library/:slug/compare",
            lazy: async () => ({ Component: (await import("@/pages/Compare")).ComparePage }),
          },
          {
            path: "clauses/:key",
            lazy: async () => ({ Component: (await import("@/pages/Clause")).ClausePage }),
          },
          {
            path: "policies",
            lazy: async () => ({ Component: (await import("@/pages/Policies")).PoliciesPage }),
          },
          {
            path: "policies/:slug/draft",
            lazy: async () => ({
              Component: (await import("@/pages/PolicyDraft")).PolicyDraftPage,
            }),
          },
          {
            path: "search",
            lazy: async () => ({ Component: (await import("@/pages/Search")).SearchPage }),
          },
          {
            path: "laws",
            lazy: async () => ({
              Component: (await import("@/pages/SelectedLaws")).SelectedLawsPage,
            }),
          },
          {
            path: "users",
            lazy: async () => ({ Component: (await import("@/pages/People")).PeoplePage }),
          },
          {
            path: "users/roles",
            lazy: async () => ({ Component: (await import("@/pages/Roles")).RolesPage }),
          },
          {
            path: "users/roles/:id",
            lazy: async () => ({ Component: (await import("@/pages/Role")).RolePage }),
          },
          {
            path: "tokens",
            lazy: async () => ({ Component: (await import("@/pages/Tokens")).TokensPage }),
          },
          {
            path: "settings",
            lazy: async () => ({ Component: (await import("@/pages/Settings")).SettingsPage }),
          },
          { path: "*", element: <NotFoundPage /> },
        ],
      },
    ],
  },
];

export const router = createBrowserRouter(routes);
