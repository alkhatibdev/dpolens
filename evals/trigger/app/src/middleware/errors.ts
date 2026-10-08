import type { NextFunction, Request, Response } from "express";
import { ZodError } from "zod";
import { logger } from "../lib/logger.js";

export function errorHandler(error: unknown, req: Request, res: Response, _next: NextFunction): void {
  if (error instanceof ZodError) {
    res.status(400).json({ error: "invalid request", issues: error.issues });
    return;
  }

  logger.error("unhandled error", { method: req.method, path: req.path, error: String(error) });
  res.status(500).json({ error: "something went wrong" });
}
