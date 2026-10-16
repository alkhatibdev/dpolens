import createClient from "openapi-fetch";

import type { components, paths } from "./schema";

export type Clause = components["schemas"]["Clause"];
export type Document = components["schemas"]["Document"];
export type DocumentInDetail = components["schemas"]["DocumentInDetail"];
export type OutlineEntry = components["schemas"]["OutlineEntry"];
export type SearchResult = components["schemas"]["Result"];
export type SignedIn = components["schemas"]["SignedIn"];
export type Person = components["schemas"]["Person"];
export type Role = components["schemas"]["RoleDocument"];
export type Permission = components["schemas"]["Permission"];
export type Token = components["schemas"]["TokenDocument"];
export type TokenMade = components["schemas"]["TokenMade"];
export type Instance = components["schemas"]["Instance"];
export type Question = components["schemas"]["Question"];
export type LoggedClause = components["schemas"]["ClauseName"];
export type Entry = components["schemas"]["Entry"];
export type Overview = components["schemas"]["Overview"];
export type Verification = components["schemas"]["Verification"];
export type Laws = components["schemas"]["Laws"];
export type LoadedLaw = components["schemas"]["LoadedLaw"];
export type InstanceSettings = components["schemas"]["InstanceSettings"];

/** An RFC 9457 problem, as the API reports every failure. */
export interface Problem {
  type: string;
  title: string;
  status: number;
  detail: string;
  reason?: string;
  /** The permission a refusal names, and every one that would have done. */
  permission?: string;
  permissions?: string[];
  /** Who changed something after it was read, and when, on an edit conflict. */
  updated_by?: string | null;
  updated_at?: string;
  revision?: number;
  /** Who holds a role that cannot be deleted. */
  holders?: string[];
  /** The open draft's number, when an upload finds one. */
  version?: number;
  /** The flags still to settle, by their place, when publishing waits for them. */
  flags?: number[];
}

export class ApiError extends Error {
  readonly status: number;
  readonly problem: Problem | null;
  /** Seconds to wait, from `Retry-After`, on a 429. */
  readonly retryAfter: number | null;

  constructor(status: number, problem: Problem | null, retryAfter: number | null = null) {
    super(problem?.detail ?? `the API answered ${status}`);
    this.status = status;
    this.problem = problem;
    this.retryAfter = retryAfter;
  }

  /** The problem's identifier, such as `session-ended`, without its prefix. */
  get kind(): string | null {
    return this.problem?.type.replace("/problems/", "") ?? null;
  }
}

// Same origin, always: the dashboard's server forwards /v1 to the API, so the
// session cookie is first-party and the browser marks every call same-origin.
export const api = createClient<paths>({
  baseUrl: globalThis.location.origin,
  credentials: "same-origin",
  // Looked up on every call rather than captured once, so tests can stand in for it.
  fetch: (request) => globalThis.fetch(request),
});

/** The body of a successful answer, or an ApiError carrying the problem. */
export async function unwrap<T>(
  call: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await call;
  if (response.ok && data !== undefined) {
    return data;
  }
  if (response.ok) {
    return undefined as T;
  }
  const problem = isProblem(error) ? error : null;
  const wait = Number(response.headers.get("Retry-After"));
  throw new ApiError(response.status, problem, Number.isFinite(wait) && wait > 0 ? wait : null);
}

function isProblem(value: unknown): value is Problem {
  return typeof value === "object" && value !== null && "type" in value && "status" in value;
}
