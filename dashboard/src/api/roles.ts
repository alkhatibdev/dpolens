import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "./client";

export function usePermissions() {
  return useQuery({
    queryKey: ["permissions"],
    staleTime: Infinity,
    queryFn: () => unwrap(api.GET("/v1/permissions")),
  });
}

export function useRoles(enabled = true) {
  return useQuery({
    queryKey: ["roles"],
    enabled,
    queryFn: () => unwrap(api.GET("/v1/roles")),
  });
}

export function useRole(id: string) {
  return useQuery({
    queryKey: ["roles", id],
    queryFn: () => unwrap(api.GET("/v1/roles/{role_id}", { params: { path: { role_id: id } } })),
  });
}

function useRefresh() {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: ["roles"] });
    void client.invalidateQueries({ queryKey: ["people"] });
  };
}

export function useCreateRole() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: (body: { name: string; description: string; permissions: string[] }) =>
      unwrap(api.POST("/v1/roles", { body })),
    onSuccess: refresh,
  });
}

export interface RoleEdit {
  id: string;
  /** The revision the change was made against, so a change made since is refused. */
  revision: number;
  name?: string;
  description?: string;
  permissions?: string[];
}

export function useEditRole() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ id, revision, ...body }: RoleEdit) =>
      unwrap(
        api.PATCH("/v1/roles/{role_id}", {
          params: { path: { role_id: id }, header: { "if-match": `"${revision}"` } },
          body,
        }),
      ),
    onSuccess: refresh,
  });
}

export function useDeleteRole() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(api.DELETE("/v1/roles/{role_id}", { params: { path: { role_id: id } } })),
    onSuccess: refresh,
  });
}
