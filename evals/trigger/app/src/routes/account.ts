import { Router } from "express";
import { z } from "zod";
import { db } from "../db.js";
import { requireUser } from "../middleware/auth.js";
import { updateProfile } from "../services/users.js";

export const accountRoutes = Router();

const profileBody = z.object({
  name: z.string().trim().min(1).max(100),
});

accountRoutes.get("/", requireUser, async (req, res) => {
  const user = await db.user.findUniqueOrThrow({
    where: { id: req.userId! },
    select: { id: true, email: true, name: true, createdAt: true },
  });
  res.json(user);
});

accountRoutes.patch("/", requireUser, async (req, res) => {
  const body = profileBody.parse(req.body);
  const user = await updateProfile(req.userId!, body);
  res.json({ id: user.id, name: user.name });
});
