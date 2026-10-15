import { Navigate } from "react-router";

import { QUERIES_READ_ALL } from "@/lib/permissions";
import { usePermitted } from "@/session";

/** Where signing in lands: the Overview for whoever may read every question, else the library. */
export function Home() {
  const can = usePermitted();
  return <Navigate to={can.has(QUERIES_READ_ALL) ? "/overview" : "/library"} replace />;
}
