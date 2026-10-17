import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "./client";
import type { components } from "./schema";

export type PolicySummary = components["schemas"]["PolicySummary"];
export type PolicyDraft = components["schemas"]["PolicyDraft"];
export type DraftClause = components["schemas"]["DraftClause"];
export type DraftFlag = components["schemas"]["FlagOut"];
export type PolicyFile = components["schemas"]["PolicyFile"];
export type FileParagraph = components["schemas"]["FileParagraph"];
export type PolicyVersion = components["schemas"]["PolicyVersion"];
export type Edit = components["schemas"]["Fix"]["edit"];
export type FlagSuggestion = components["schemas"]["FlagSuggestion"];
export type SplitPlace = components["schemas"]["SplitPlace"];
export type Candidate = components["schemas"]["Candidate"];
export type PolicyVersions = components["schemas"]["PolicyVersions"];
export type VersionEntry = components["schemas"]["VersionEntry"];
export type PolicyComparison = components["schemas"]["PolicyComparison"];
export type ComparedClause = components["schemas"]["ComparedClause"];

export function usePolicies(enabled = true) {
  return useQuery({
    queryKey: ["policies"],
    enabled,
    queryFn: () => unwrap(api.GET("/v1/policies")),
  });
}

const draftKey = (slug: string) => ["policies", slug, "draft"];
const versionsKey = (slug: string) => ["policies", slug, "versions"];

/** A policy's versions; the draft is among them only for those who review policies. */
export function usePolicyVersions(slug: string, enabled = true) {
  return useQuery({
    queryKey: versionsKey(slug),
    enabled,
    queryFn: () => unwrap(api.GET("/v1/policies/{slug}/versions", { params: { path: { slug } } })),
  });
}

/** Two published versions compared, clause by clause. Published versions never change. */
export function useComparison(slug: string, from: number | null, to: number | null) {
  return useQuery({
    queryKey: ["policies", slug, "compare", from, to],
    enabled: from !== null && to !== null && from !== to,
    staleTime: Infinity,
    placeholderData: keepPreviousData,
    queryFn: () =>
      unwrap(
        api.GET("/v1/policies/{slug}/compare", {
          params: { path: { slug }, query: { from: from ?? 0, to: to ?? 0 } },
        }),
      ),
  });
}

export function useDraft(slug: string) {
  return useQuery({
    queryKey: draftKey(slug),
    queryFn: () => unwrap(api.GET("/v1/policies/{slug}/draft", { params: { path: { slug } } })),
  });
}

/** A version's file as DPOLens read it. It never changes, so it is read once. */
export function usePolicyFile(slug: string, number: number | undefined) {
  return useQuery({
    queryKey: ["policies", slug, "file", number],
    enabled: number !== undefined,
    staleTime: Infinity,
    queryFn: () =>
      unwrap(
        api.GET("/v1/policies/{slug}/versions/{number}/file", {
          params: { path: { slug, number: number ?? 0 } },
        }),
      ),
  });
}

export interface Upload {
  file: File;
  /** The policy a new version is for; a new policy when left out. */
  of?: string;
  slug?: string;
  title?: string;
  effectiveDate?: string;
  label?: string;
  replace?: boolean;
}

/** The file itself is the request body, with its name in the query, as the API takes it. */
export function useUpload() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ file, of, slug, title, effectiveDate, label, replace }: Upload) => {
      const body = file as unknown as string;
      const sent = {
        bodySerializer: (value: unknown) => value as BodyInit,
        headers: { "Content-Type": "application/octet-stream" },
      };
      const common = {
        filename: file.name,
        effective_date: effectiveDate || undefined,
        version_label: label || undefined,
      };
      return unwrap(
        of
          ? api.POST("/v1/policies/{slug}/versions", {
              params: { path: { slug: of }, query: { ...common, replace } },
              body,
              ...sent,
            })
          : api.POST("/v1/policies", {
              params: { query: { ...common, slug: slug || undefined, title: title || undefined } },
              body,
              ...sent,
            }),
      );
    },
    onSuccess: (draft) => {
      client.setQueryData(draftKey(draft.version.slug), draft);
      void client.invalidateQueries({ queryKey: ["policies"], exact: true });
      void client.invalidateQueries({ queryKey: versionsKey(draft.version.slug) });
    },
  });
}

/** What every change to a draft carries: the revision it was made against. */
interface Change {
  revision: number;
}

function ifMatch(revision: number) {
  return { "if-match": `"${revision}"` };
}

/**
 * A change to a draft. The answer is the draft as it now stands, shown at once,
 * so the next change carries the new revision rather than conflicting with this one.
 */
function useDraftChange<T extends Change>(slug: string, call: (change: T) => Promise<PolicyDraft>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: call,
    onSuccess: (draft) => {
      client.setQueryData(draftKey(slug), draft);
      void client.invalidateQueries({ queryKey: ["policies"], exact: true });
    },
  });
}

export function useAcceptFlags(slug: string) {
  return useDraftChange(slug, ({ revision, positions }: Change & { positions: number[] }) =>
    unwrap(
      api.POST("/v1/policies/{slug}/draft/flags/accept", {
        params: { path: { slug }, header: ifMatch(revision) },
        body: { positions },
      }),
    ),
  );
}

export interface Fixing extends Change {
  edit: Edit;
  key: string;
  at?: number;
}

/** A fix to how a clause was read. The answer names the key the clause has now. */
export function useFixClause(slug: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ revision, ...body }: Fixing) =>
      unwrap(
        api.POST("/v1/policies/{slug}/draft/edits", {
          params: { path: { slug }, header: ifMatch(revision) },
          body,
        }),
      ),
    onSuccess: (fixed) => {
      client.setQueryData(draftKey(slug), fixed);
      void client.invalidateQueries({ queryKey: ["policies"], exact: true });
    },
  });
}

/** Say a new clause is the same rule as a clause of the version before that nothing continues. */
export function useSameRule(slug: string) {
  return useDraftChange(
    slug,
    ({ revision, key, continues }: Change & { key: string; continues: string }) =>
      unwrap(
        api.POST("/v1/policies/{slug}/draft/matches/{key}", {
          params: { path: { slug, key }, header: ifMatch(revision) },
          body: { continues },
        }),
      ),
  );
}

export function useRejectMatch(slug: string) {
  return useDraftChange(slug, ({ revision, key }: Change & { key: string }) =>
    unwrap(
      api.POST("/v1/policies/{slug}/draft/matches/{key}/reject", {
        params: { path: { slug, key }, header: ifMatch(revision) },
      }),
    ),
  );
}

export interface Details extends Change {
  title?: string;
  effective_date?: string;
  version_label?: string;
}

export function useEditDraft(slug: string) {
  return useDraftChange(slug, ({ revision, ...body }: Details) =>
    unwrap(
      api.PATCH("/v1/policies/{slug}/draft", {
        params: { path: { slug }, header: ifMatch(revision) },
        body,
      }),
    ),
  );
}

export function usePublish(slug: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ revision }: Change) =>
      unwrap(
        api.POST("/v1/policies/{slug}/draft/publish", {
          params: { path: { slug }, header: ifMatch(revision) },
        }),
      ),
    onSuccess: () => {
      client.removeQueries({ queryKey: draftKey(slug) });
      void client.invalidateQueries({ queryKey: ["policies"], exact: true });
      void client.invalidateQueries({ queryKey: versionsKey(slug) });
      void client.invalidateQueries({ queryKey: ["documents"] });
      void client.invalidateQueries({ queryKey: ["document", slug] });
    },
  });
}

export function useDiscard(slug: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ revision }: Change) =>
      unwrap(
        api.DELETE("/v1/policies/{slug}/draft", {
          params: { path: { slug }, header: ifMatch(revision) },
        }),
      ),
    onSuccess: () => {
      client.removeQueries({ queryKey: draftKey(slug) });
      void client.invalidateQueries({ queryKey: ["policies"], exact: true });
      void client.invalidateQueries({ queryKey: versionsKey(slug) });
    },
  });
}

export function useArchive() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (slug: string) =>
      unwrap(api.POST("/v1/policies/{slug}/archive", { params: { path: { slug } } })),
    onSuccess: (_, slug) => {
      client.removeQueries({ queryKey: draftKey(slug) });
      void client.invalidateQueries({ queryKey: ["policies"], exact: true });
      void client.invalidateQueries({ queryKey: ["documents"] });
    },
  });
}
