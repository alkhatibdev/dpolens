import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "./client";

const PEOPLE = ["people"] as const;

export function usePeople(enabled = true) {
  return useQuery({
    queryKey: PEOPLE,
    enabled,
    queryFn: () => unwrap(api.GET("/v1/users")),
  });
}

/** Everything that changes a person also changes the lists of people and roles. */
function useRefresh() {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: PEOPLE });
    void client.invalidateQueries({ queryKey: ["roles"] });
  };
}

export function useAddPerson() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: (body: { email: string; display_name: string; roles: string[] }) =>
      unwrap(api.POST("/v1/users", { body })),
    onSuccess: refresh,
  });
}

export function useChangeStatus() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: "active" | "deactivated" }) =>
      unwrap(
        api.PATCH("/v1/users/{user_id}", { params: { path: { user_id: id } }, body: { status } }),
      ),
    onSuccess: refresh,
  });
}

export function useSetRoles() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ id, roles }: { id: string; roles: string[] }) =>
      unwrap(
        api.PUT("/v1/users/{user_id}/roles", {
          params: { path: { user_id: id } },
          body: { roles },
        }),
      ),
    onSuccess: refresh,
  });
}

export function useMakeLink() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(api.POST("/v1/users/{user_id}/sign-in-links", { params: { path: { user_id: id } } })),
    onSuccess: refresh,
  });
}

/** Where a sign-in link's secret is spent: after `#`, so it reaches no server log. */
export function linkFor(secret: string): string {
  return `${globalThis.location.origin}/welcome#${secret}`;
}
