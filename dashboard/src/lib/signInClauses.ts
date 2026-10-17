/**
 * The two clauses the sign-in pages quote, one rule in both laws. Nobody is
 * signed in there, so nothing is read from the instance: they are fixed here,
 * word for word as the packs hold them, and a test reads the packs to keep them
 * so.
 */
export const SIGN_IN_CLAUSES = {
  gdpr: {
    key: "gdpr:art-17:para-1:pt-a",
    version: "2026.1",
    effective: "2018-05-25",
    text: "the personal data are no longer necessary in relation to the purposes for which they were collected or otherwise processed;",
  },
  uae: {
    key: "uae-pdpl:art-15:para-2:pt-a",
    effective: "2022-01-02",
    text: "لم تعد بياناته الشخصية ضرورية للأغراض التي جُمعت أو عولجت من أجلها.",
  },
} as const;
