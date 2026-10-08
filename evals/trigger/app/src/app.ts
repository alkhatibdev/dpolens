import express from "express";
import { errorHandler } from "./middleware/errors.js";
import { requestLogger } from "./middleware/requestLogger.js";
import { accountRoutes } from "./routes/account.js";
import { authRoutes } from "./routes/auth.js";
import { orderRoutes } from "./routes/orders.js";
import { productRoutes } from "./routes/products.js";

export function createApp() {
  const app = express();

  app.use(express.json());
  app.use(requestLogger);
  app.use(express.static("public"));

  app.use("/auth", authRoutes);
  app.use("/products", productRoutes);
  app.use("/orders", orderRoutes);
  app.use("/account", accountRoutes);

  app.use(errorHandler);
  return app;
}
