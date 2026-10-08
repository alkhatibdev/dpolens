import { config } from "../config.js";
import { logger } from "./logger.js";

const SEGMENT_TRACK_URL = "https://api.segment.io/v1/track";

export async function track(event: string, properties: Record<string, unknown> = {}): Promise<void> {
  if (!config.segmentWriteKey) {
    return;
  }

  try {
    await fetch(SEGMENT_TRACK_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Basic ${Buffer.from(`${config.segmentWriteKey}:`).toString("base64")}`,
      },
      body: JSON.stringify({
        anonymousId: "server",
        event,
        properties,
        timestamp: new Date().toISOString(),
      }),
    });
  } catch (error) {
    logger.warn("analytics event dropped", { event, error: String(error) });
  }
}
