import { vi } from "vitest";

type Answer = { status?: number; body?: unknown; headers?: Record<string, string> };
type Handler = (request: Request) => Answer | Promise<Answer>;

/**
 * Stand in for the API: each route is "METHOD /path", answered with a status and
 * a body. Anything unrouted is a 404 problem, so a test that forgets a route fails
 * loudly rather than hanging.
 */
export function serve(routes: Record<string, Handler | Answer>) {
  const calls: Request[] = [];
  const fetch = vi.fn(async (input: Request) => {
    calls.push(input.clone());
    const url = new URL(input.url);
    const route = routes[`${input.method} ${url.pathname}`];
    const answer = typeof route === "function" ? await route(input) : route;
    const status = answer?.status ?? (answer ? 200 : 404);
    const body =
      answer?.body ??
      (answer ? undefined : { type: "/problems/not-found", title: "", status: 404, detail: "" });
    const problem = status >= 400;
    return new Response(status === 204 || body === undefined ? null : JSON.stringify(body), {
      status,
      headers: {
        "Content-Type": problem ? "application/problem+json" : "application/json",
        ...answer?.headers,
      },
    });
  });
  vi.stubGlobal("fetch", fetch);
  return { calls, fetch };
}

export function problem(kind: string, status: number, extra: Record<string, unknown> = {}) {
  return {
    status,
    body: { type: `/problems/${kind}`, title: kind, status, detail: kind, ...extra },
  };
}
