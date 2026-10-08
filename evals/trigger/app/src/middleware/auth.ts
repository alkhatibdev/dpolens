import type { NextFunction, Request, Response } from "express";
import { db } from "../db.js";

declare global {
  namespace Express {
    interface Request {
      userId?: number;
    }
  }
}

export async function requireUser(req: Request, res: Response, next: NextFunction): Promise<void> {
  const header = req.header("authorization") ?? "";
  const token = header.startsWith("Bearer ") ? header.slice("Bearer ".length) : "";

  if (!token) {
    res.status(401).json({ error: "sign in required" });
    return;
  }

  const session = await db.session.findUnique({ where: { id: token } });
  if (!session || session.expiresAt < new Date()) {
    res.status(401).json({ error: "session expired, sign in again" });
    return;
  }

  req.userId = session.userId;
  next();
}
