import { config } from "../config.js";
import { logger } from "./logger.js";

const POSTMARK_URL = "https://api.postmarkapp.com/email";

export async function sendEmail(to: string, subject: string, html: string): Promise<void> {
  if (!config.postmarkToken) {
    logger.debug("email not sent, no Postmark token", { subject });
    return;
  }

  const response = await fetch(POSTMARK_URL, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "X-Postmark-Server-Token": config.postmarkToken,
    },
    body: JSON.stringify({ From: config.mailFrom, To: to, Subject: subject, HtmlBody: html }),
  });

  if (!response.ok) {
    logger.error("email failed", { subject, status: response.status });
  }
}
