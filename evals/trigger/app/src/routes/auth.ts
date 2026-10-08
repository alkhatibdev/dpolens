import { Router } from "express";
import { z } from "zod";
import { sendEmail } from "../lib/mailer.js";
import { checkPassword, createUser, findUserByEmail, startSession } from "../services/users.js";

export const authRoutes = Router();

const signupBody = z.object({
  email: z.email(),
  name: z.string().trim().min(1).max(100),
  password: z.string().min(10),
});

const loginBody = z.object({
  email: z.email(),
  password: z.string(),
});

authRoutes.post("/signup", async (req, res) => {
  const body = signupBody.parse(req.body);

  if (await findUserByEmail(body.email)) {
    res.status(409).json({ error: "an account with that email already exists" });
    return;
  }

  const user = await createUser(body);
  await sendEmail(
    user.email,
    "Welcome to Larder",
    `<p>Hi ${user.name}, thanks for joining Larder. Your first delivery is on us.</p>`,
  );

  const session = await startSession(user.id);
  res.status(201).json({ id: user.id, token: session.token, expiresAt: session.expiresAt });
});

authRoutes.post("/login", async (req, res) => {
  const body = loginBody.parse(req.body);
  const user = await findUserByEmail(body.email);

  if (!user || !(await checkPassword(user, body.password))) {
    res.status(401).json({ error: "wrong email or password" });
    return;
  }

  const session = await startSession(user.id);
  res.json({ token: session.token, expiresAt: session.expiresAt });
});
