import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { api, unwrap } from "./client";

export type Surface = "dashboard" | "mcp" | "api" | "slack" | "github_action";
export type Status = "ok" | "no_match" | "refused" | "error";
export type Operation =
  "search" | "get_clause" | "get_subtree" | "list_documents" | "get_document" | "ask";

export interface QuestionFilter {
  since?: string;
  surface?: Surface[];
  status?: Status[];
  operation?: Operation[];
  document?: string;
  q?: string;
  asked_by?: string;
  identities?: boolean;
}

export function useQuestions(filter: QuestionFilter, before: string | null) {
  return useQuery({
    queryKey: ["queries", filter, before],
    placeholderData: keepPreviousData,
    queryFn: () =>
      unwrap(
        api.GET("/v1/queries", {
          params: { query: { ...filter, ...(before ? { before } : {}), limit: 25 } },
        }),
      ),
  });
}

export type Category =
  "sign_ins" | "people" | "roles" | "tokens" | "laws" | "policies" | "questions" | "exports";

export interface EntryFilter {
  actor?: string;
  category?: Category[];
  since?: string;
  q?: string;
}

export function useEntries(filter: EntryFilter, before: number | null) {
  return useQuery({
    queryKey: ["governance", "entries", filter, before],
    placeholderData: keepPreviousData,
    queryFn: () =>
      unwrap(
        api.GET("/v1/governance/entries", {
          params: { query: { ...filter, ...(before ? { before } : {}), limit: 25 } },
        }),
      ),
  });
}

export function useActors() {
  return useQuery({
    queryKey: ["governance", "actors"],
    queryFn: () => unwrap(api.GET("/v1/governance/actors")),
  });
}

/** Recomputed on every visit: the point is that it was checked now, not a minute ago. */
export function useVerification(enabled = true) {
  return useQuery({
    queryKey: ["governance", "verification"],
    enabled,
    staleTime: 0,
    queryFn: () => unwrap(api.GET("/v1/governance/verification")),
  });
}

/** The reader's own time zone, so "today" on a chart is today where they are. */
export function readerZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}

export function useOverview(days: number, enabled = true) {
  const tz = readerZone();
  return useQuery({
    queryKey: ["overview", days, tz],
    enabled,
    queryFn: () => unwrap(api.GET("/v1/overview", { params: { query: { days, tz } } })),
  });
}

export function useClauseActivity(key: string, enabled: boolean) {
  const tz = readerZone();
  return useQuery({
    queryKey: ["activity", key, tz],
    enabled,
    queryFn: () =>
      unwrap(
        api.GET("/v1/clauses/{key}/activity", {
          params: { path: { key }, query: { days: 7, tz } },
        }),
      ),
  });
}
