import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, useLocation } from "react-router";

import { endedBecause, useSession } from "@/session";

/** The pages behind sign-in. Anyone else is sent to sign in, and brought back after. */
export function RequireSession({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const location = useLocation();
  const session = useSession();

  if (session.status === "pending") {
    return (
      <div className="grid min-h-dvh place-items-center text-muted" role="status">
        {t("app.loading")}
      </div>
    );
  }
  const reason = endedBecause(session.error);
  if (session.status === "error") {
    const query = reason && reason !== "unknown" ? `?reason=${reason}` : "";
    return <Navigate to={`/sign-in${query}`} state={{ from: location }} replace />;
  }
  return children;
}
