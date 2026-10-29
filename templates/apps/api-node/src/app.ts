import express from "express";
import { itemsRouter } from "./items.js";
import { MemoryStore, type Store } from "./store.js";

/** Builds the app; tests pass their own store. */
export function createApp(store: Store = new MemoryStore()): express.Express {
  const app = express();
  app.use(express.json({ limit: "1mb" }));
  app.use((req, res, next) => {
    const start = process.hrtime.bigint();
    res.on("finish", () => {
      const ms = Number(process.hrtime.bigint() - start) / 1e6;
      console.log(`${req.method} ${req.path} -> ${res.statusCode} in ${ms.toFixed(1)} ms`);
    });
    next();
  });
  app.get("/health", (_req, res) => {
    res.json({ status: "ok" });
  });
  app.use("/api/items", itemsRouter(store));
  app.use((err: Error, _req: express.Request, res: express.Response, _next: express.NextFunction) => {
    const status = err instanceof SyntaxError ? 400 : 500;
    res.status(status).json({ error: status === 400 ? "invalid JSON body" : "internal error" });
  });
  return app;
}
