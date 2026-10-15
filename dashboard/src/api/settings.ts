import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "./client";

export function useSettings(enabled = true) {
  return useQuery({
    queryKey: ["settings"],
    enabled,
    queryFn: () => unwrap(api.GET("/v1/settings")),
  });
}
