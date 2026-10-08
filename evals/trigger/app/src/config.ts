export const config = {
  port: Number(process.env.PORT ?? 3000),
  sessionDays: Number(process.env.SESSION_DAYS ?? 30),
  segmentWriteKey: process.env.SEGMENT_WRITE_KEY ?? "",
  postmarkToken: process.env.POSTMARK_TOKEN ?? "",
  mailFrom: process.env.MAIL_FROM ?? "Larder <hello@larder.shop>",
};
