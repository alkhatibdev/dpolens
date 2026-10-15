import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";

import { ApiError, api, unwrap, type SignedIn } from "@/api/client";

export const SESSION = ["session"] as const;

export function useSession() {
  return useQuery({
    queryKey: SESSION,
    queryFn: () => unwrap(api.GET("/v1/sessions/current")),
    retry: false,
    staleTime: 60_000,
  });
}

export function useSignIn() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { email: string; password: string }) =>
      unwrap(api.POST("/v1/sessions", { body })),
    onSuccess: (signedIn: SignedIn) => client.setQueryData(SESSION, signedIn),
  });
}

export function useSignOut() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.DELETE("/v1/sessions/current")),
    // Every answer cached for this person goes; the mutation itself stays, so the
    // caller's own callback still runs.
    onSettled: () => client.removeQueries(),
  });
}

/** Why the session ended, read from a refusal, for the sign-in page to say. */
export function endedBecause(error: unknown): string | null {
  if (error instanceof ApiError && error.status === 401) {
    return error.problem?.reason ?? "unknown";
  }
  return null;
}

export function useChangePassword() {
  return useMutation({
    mutationFn: (body: { current: string; new: string }) =>
      unwrap(api.PUT("/v1/sessions/current/password", { body })),
  });
}

/** Spend a sign-in link: the password is set and the person is signed in. */
export function useSpendLink() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { secret: string; password: string }) =>
      unwrap(api.POST("/v1/sessions/from-link", { body })),
    onSuccess: (signedIn: SignedIn) => client.setQueryData(SESSION, signedIn),
  });
}

/** What the signed-in person may do, for showing only what they can use. */
export function usePermitted(): ReadonlySet<string> {
  const session = useSession();
  const permissions = session.data?.permissions;
  return useMemo(() => new Set(permissions ?? []), [permissions]);
}
