import { Router } from "express";
import { db } from "../db.js";
import { formatPrice } from "../lib/money.js";

export const productRoutes = Router();

productRoutes.get("/", async (req, res) => {
  const category = typeof req.query.category === "string" ? req.query.category : undefined;

  const products = await db.product.findMany({
    where: category ? { category: { slug: category } } : {},
    orderBy: { name: "asc" },
  });

  res.json(products.map((product) => ({ ...product, price: formatPrice(product.priceCents) })));
});

productRoutes.get("/:slug", async (req, res) => {
  const product = await db.product.findUnique({
    where: { slug: req.params.slug },
    include: { category: true },
  });

  if (!product) {
    res.status(404).json({ error: "no such product" });
    return;
  }

  res.json({ ...product, price: formatPrice(product.priceCents) });
});
