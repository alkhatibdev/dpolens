import { db } from "../db.js";
import { track } from "../lib/analytics.js";
import { orderTotal } from "../lib/money.js";

export interface NewOrder {
  items: { productId: number; quantity: number }[];
  deliveryAddress: string;
  deliveryPostcode: string;
}

export class UnknownProduct extends Error {}

export async function placeOrder(userId: number, input: NewOrder) {
  const products = await db.product.findMany({
    where: { id: { in: input.items.map((item) => item.productId) } },
  });

  const lines = input.items.map((item) => {
    const product = products.find((candidate) => candidate.id === item.productId);
    if (!product) {
      throw new UnknownProduct(`no product with id ${item.productId}`);
    }
    return { productId: product.id, quantity: item.quantity, priceCents: product.priceCents };
  });

  const totalCents = orderTotal(lines);
  const order = await db.order.create({
    data: {
      userId,
      totalCents,
      deliveryAddress: input.deliveryAddress,
      deliveryPostcode: input.deliveryPostcode,
      items: { create: lines },
    },
    include: { items: true },
  });

  await track("order_placed", { orderId: order.id, totalCents, itemCount: lines.length });
  return order;
}

export async function listOrders(userId: number) {
  return db.order.findMany({
    where: { userId },
    include: { items: true },
    orderBy: { createdAt: "desc" },
  });
}
