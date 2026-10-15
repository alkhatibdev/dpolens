import { uae } from "./fixtures";

/** What the library's first page asks for, for a test that lands on it. */
export const library = {
  "GET /v1/documents": { body: { documents: [uae], total: 1, limit: 100, offset: 0 } },
};
