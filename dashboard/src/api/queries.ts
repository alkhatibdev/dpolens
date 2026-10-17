import { keepPreviousData, useQueries, useQuery } from "@tanstack/react-query";

import { api, unwrap, type Clause } from "./client";

export function useDocuments(enabled = true) {
  return useQuery({
    queryKey: ["documents"],
    enabled,
    queryFn: () => unwrap(api.GET("/v1/documents", { params: { query: { limit: 100 } } })),
  });
}

/** A document as it stood on `asOf`, or as it is in force today. */
export function useDocument(slug: string, lang?: string, asOf?: string | null) {
  return useQuery({
    queryKey: ["document", slug, lang, asOf ?? null],
    queryFn: () =>
      unwrap(
        api.GET("/v1/documents/{slug}", {
          params: { path: { slug }, query: { lang, as_of: asOf ?? undefined } },
        }),
      ),
  });
}

export function useClause(key: string, lang?: string, enabled = true, asOf?: string | null) {
  return useQuery({
    queryKey: ["clause", key, lang, asOf ?? null],
    enabled,
    queryFn: () =>
      unwrap(
        api.GET("/v1/clauses/{key}", {
          params: { path: { key }, query: { lang, as_of: asOf ?? undefined } },
        }),
      ),
  });
}

/**
 * A clause and everything beneath it, once in each language asked for. A
 * translation's points are numbered in its own words, so each language is read
 * as itself rather than taken from another's `authoritative_text`.
 */
export function useSubtrees(
  key: string | null,
  languages: readonly string[],
  asOf?: string | null,
) {
  return useQueries({
    queries: languages.map((lang) => ({
      queryKey: ["subtree", key, lang, asOf ?? null],
      enabled: key !== null,
      placeholderData: keepPreviousData,
      queryFn: () =>
        unwrap(
          api.GET("/v1/clauses/{key}/subtree", {
            params: { path: { key: key ?? "" }, query: { lang, as_of: asOf ?? undefined } },
          }),
        ),
    })),
    combine: (answers) => ({
      byLanguage: Object.fromEntries(
        languages.map((lang, index) => [lang, answers[index]?.data ?? []]),
      ) as Record<string, Clause[]>,
      isPending: answers.some((answer) => answer.isPending),
      error: answers.find((answer) => answer.error)?.error ?? null,
      refetch: () => answers.forEach((answer) => void answer.refetch()),
    }),
  });
}

export interface SearchOptions {
  query: string;
  laws: string[];
  asOf: string | null;
  lang: string | null;
  includeExplanatory: boolean;
}

export function useSearch(options: SearchOptions) {
  return useQuery({
    queryKey: ["search", options],
    enabled: options.query.trim().length > 0,
    placeholderData: keepPreviousData,
    queryFn: () =>
      unwrap(
        api.POST("/v1/search", {
          body: {
            query: options.query,
            limit: 10,
            laws: options.laws.length ? options.laws : null,
            as_of: options.asOf,
            lang: options.lang,
            include_explanatory: options.includeExplanatory,
            expand: "none",
            explain: false,
          },
        }),
      ),
  });
}
