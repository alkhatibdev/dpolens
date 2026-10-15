import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap, type Laws } from "./client";

export const LAWS = ["laws"] as const;

export const lawsQuery = {
  queryKey: LAWS,
  queryFn: () => unwrap(api.GET("/v1/laws")),
};

export function useLaws(enabled = true) {
  return useQuery({ ...lawsQuery, enabled });
}

/** Nobody has ever chosen, not even to go back to every law: the dashboard asks at sign-in. */
export function neverChosen(laws: Laws): boolean {
  return laws.selected === null && laws.changed === null;
}

/**
 * The answer is the selection as saved, shown at once. Every other answer that says
 * whether a law is selected, or that searched with the old selection, is read again.
 */
function useSaved() {
  const client = useQueryClient();
  return (saved: Laws) => {
    client.setQueryData(LAWS, saved);
    for (const key of ["documents", "document", "clause", "subtree", "search", "overview"]) {
      void client.invalidateQueries({ queryKey: [key] });
    }
  };
}

export function useChooseLaws() {
  const saved = useSaved();
  return useMutation({
    mutationFn: (laws: string[]) => unwrap(api.PUT("/v1/laws/selection", { body: { laws } })),
    onSuccess: saved,
  });
}

export function useSearchEveryLaw() {
  const saved = useSaved();
  return useMutation({
    mutationFn: () => unwrap(api.DELETE("/v1/laws/selection")),
    onSuccess: saved,
  });
}
