import { Router } from "express";
import type { Store } from "./store.js";

/** The /api/items routes. */
export function itemsRouter(store: Store): Router {
  const router = Router();

  const parseId = (raw: string | undefined): number | undefined => {
    const id = Number(raw);
    return Number.isInteger(id) && id > 0 ? id : undefined;
  };

  const parseBody = (body: unknown): { name: string; done: boolean } | undefined => {
    if (typeof body !== "object" || body === null) return undefined;
    const { name, done } = body as { name?: unknown; done?: unknown };
    if (typeof name !== "string" || name.trim() === "" || name.length > 200) return undefined;
    return { name: name.trim(), done: done === true };
  };

  router.get("/", (_req, res) => {
    res.json(store.list());
  });

  router.post("/", (req, res) => {
    const body = parseBody(req.body);
    if (!body) return void res.status(422).json({ error: "name is required" });
    res.status(201).json(store.create(body.name));
  });

  router.get("/:id", (req, res) => {
    const id = parseId(req.params.id);
    if (id === undefined) return void res.status(400).json({ error: "id must be a positive number" });
    const item = store.get(id);
    if (!item) return void res.status(404).json({ error: "item not found" });
    res.json(item);
  });

  router.put("/:id", (req, res) => {
    const id = parseId(req.params.id);
    if (id === undefined) return void res.status(400).json({ error: "id must be a positive number" });
    const body = parseBody(req.body);
    if (!body) return void res.status(422).json({ error: "name is required" });
    const item = store.update(id, body.name, body.done);
    if (!item) return void res.status(404).json({ error: "item not found" });
    res.json(item);
  });

  router.delete("/:id", (req, res) => {
    const id = parseId(req.params.id);
    if (id === undefined) return void res.status(400).json({ error: "id must be a positive number" });
    if (!store.remove(id)) return void res.status(404).json({ error: "item not found" });
    res.status(204).end();
  });

  return router;
}
