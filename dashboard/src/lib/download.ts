import { ApiError } from "@/api/client";

/**
 * Fetch a file from the API and hand it to the browser as a download, with the
 * name the API gives it. The session cookie goes with the request like any other.
 */
export async function download(path: string, init: RequestInit = {}): Promise<void> {
  const response = await globalThis.fetch(
    new Request(`${globalThis.location.origin}${path}`, {
      credentials: "same-origin",
      ...init,
    }),
  );
  if (!response.ok) {
    throw new ApiError(response.status, null);
  }
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const name = /filename="([^"]+)"/.exec(disposition)?.[1] ?? "dpolens-export";
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  // Revoked on the next turn, once the browser has taken the file.
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

/** A query string from a filter, repeating a key for each value of a list. */
export function queryString(values: Record<string, unknown>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (Array.isArray(value)) {
      value.forEach((item) => params.append(key, String(item)));
    } else if (value !== undefined && value !== null && value !== "" && value !== false) {
      params.append(key, String(value));
    }
  }
  const text = params.toString();
  return text ? `?${text}` : "";
}
