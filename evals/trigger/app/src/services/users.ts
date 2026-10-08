import bcrypt from "bcryptjs";
import { randomBytes } from "node:crypto";
import { config } from "../config.js";
import { db } from "../db.js";

const DAY_MS = 24 * 60 * 60 * 1000;

export async function createUser(input: { email: string; name: string; password: string }) {
  const passwordHash = await bcrypt.hash(input.password, 12);
  return db.user.create({
    data: { email: input.email.toLowerCase(), name: input.name, passwordHash },
  });
}

export async function findUserByEmail(email: string) {
  return db.user.findUnique({ where: { email: email.toLowerCase() } });
}

export async function checkPassword(user: { passwordHash: string }, password: string) {
  return bcrypt.compare(password, user.passwordHash);
}

export async function startSession(userId: number) {
  const id = randomBytes(32).toString("hex");
  const expiresAt = new Date(Date.now() + config.sessionDays * DAY_MS);
  await db.session.create({ data: { id, userId, expiresAt } });
  return { token: id, expiresAt };
}

export async function updateProfile(userId: number, changes: { name?: string }) {
  return db.user.update({ where: { id: userId }, data: changes });
}
