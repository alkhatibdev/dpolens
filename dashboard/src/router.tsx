import { createBrowserRouter, Navigate } from "react-router";

import { Shell } from "@/layout/Shell";
import { ClausePage } from "@/pages/Clause";
import { DocumentPage } from "@/pages/Document";
import { LibraryPage } from "@/pages/Library";
import { NotFoundPage } from "@/pages/NotFound";
import { PeoplePage } from "@/pages/People";
import { RolePage } from "@/pages/Role";
import { RolesPage } from "@/pages/Roles";
import { SearchPage } from "@/pages/Search";
import { SignInPage } from "@/pages/SignIn";
import { TokensPage } from "@/pages/Tokens";
import { WelcomePage } from "@/pages/Welcome";
import { RequireSession } from "@/RequireSession";

export const routes = [
  { path: "/sign-in", element: <SignInPage /> },
  { path: "/welcome", element: <WelcomePage /> },
  {
    path: "/",
    element: (
      <RequireSession>
        <Shell />
      </RequireSession>
    ),
    children: [
      { index: true, element: <Navigate to="/library" replace /> },
      { path: "library", element: <LibraryPage /> },
      { path: "library/:slug", element: <DocumentPage /> },
      { path: "clauses/:key", element: <ClausePage /> },
      { path: "search", element: <SearchPage /> },
      { path: "users", element: <PeoplePage /> },
      { path: "users/roles", element: <RolesPage /> },
      { path: "users/roles/:id", element: <RolePage /> },
      { path: "tokens", element: <TokensPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];

export const router = createBrowserRouter(routes);
