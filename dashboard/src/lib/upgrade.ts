import { createPath, type Path } from "react-router";

const RELOADED_AT = "dpolens.reloadedAt";

/** Long enough for a fresh load to have finished, so a second failure is not an upgrade. */
const PAUSE_MS = 10_000;

/**
 * Where to load from the server when a page's file cannot be fetched, or null to
 * leave the error showing.
 *
 * An upgrade replaces the dashboard's files, and a tab opened before it still asks
 * for the old ones. A full load of the page somebody was opening brings the new
 * files. When the last full load for this reason was moments ago, the file is
 * missing for some other reason, and loading again would only repeat.
 */
export function reloadTarget(
  opening: Partial<Path> | undefined,
  current: string,
  storage: () => Storage,
  now: number = Date.now(),
): string | null {
  try {
    const store = storage();
    if (now - Number(store.getItem(RELOADED_AT)) < PAUSE_MS) {
      return null;
    }
    store.setItem(RELOADED_AT, String(now));
  } catch {
    // Without anywhere to note the attempt, a reload could repeat for ever.
    return null;
  }
  return opening ? createPath(opening) : current;
}
