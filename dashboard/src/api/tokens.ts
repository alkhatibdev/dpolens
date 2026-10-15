import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "./client";

export function useTokens(everyone: boolean, enabled = true) {
  return useQuery({
    queryKey: ["tokens", everyone ? "everyone" : "mine"],
    enabled,
    queryFn: () => unwrap(api.GET("/v1/tokens", { params: { query: { everyone } } })),
  });
}

function useRefresh() {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: ["tokens"] });
    void client.invalidateQueries({ queryKey: ["people"] });
  };
}

export function useMakeToken() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: (body: { name: string; permissions: string[]; expires_at: string | null }) =>
      unwrap(api.POST("/v1/tokens", { body })),
    onSuccess: refresh,
  });
}

export function useRevokeToken() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(api.DELETE("/v1/tokens/{token_id}", { params: { path: { token_id: id } } })),
    onSuccess: refresh,
  });
}

export function useInstance() {
  return useQuery({
    queryKey: ["instance"],
    staleTime: Infinity,
    queryFn: () => unwrap(api.GET("/v1/instance")),
  });
}
