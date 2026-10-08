import { Router } from "express";
import { z } from "zod";
import { requireUser } from "../middleware/auth.js";
import { listOrders, placeOrder, UnknownProduct } from "../services/orders.js";

export const orderRoutes = Router();

const orderBody = z.object({
  items: z
    .array(z.object({ productId: z.number().int(), quantity: z.number().int() }))
    .min(1),
  deliveryAddress: z.string().trim().min(5),
  deliveryPostcode: z.string().trim().min(3),
});

orderRoutes.post("/", requireUser, async (req, res) => {
  const body = orderBody.parse(req.body);

  try {
    const order = await placeOrder(req.userId!, body);
    res.status(201).json(order);
  } catch (error) {
    if (error instanceof UnknownProduct) {
      res.status(400).json({ error: error.message });
      return;
    }
    throw error;
  }
});

orderRoutes.get("/", requireUser, async (req, res) => {
  res.json(await listOrders(req.userId!));
});
