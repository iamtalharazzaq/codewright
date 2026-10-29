import express from "express";
import { checkPassword, hashPassword, makeToken, readToken } from "./security.js";
import type { Store, User } from "./store.js";

type Handler = (req: express.Request, res: express.Response, user: User) => Promise<void>;

const publicUser = (u: User) => ({ id: u.id, email: u.email, is_admin: u.isAdmin });
const itemJson = (i: { id: number; name: string; done: boolean }) => ({ id: i.id, name: i.name, done: i.done });

/** Builds the app; tests pass a MemoryStore. */
export function createApp(store: Store, secret: string): express.Express {
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

  /** Runs `next` for a signed-in user, or answers 401. */
  const signedIn =
    (next: Handler): express.RequestHandler =>
    async (req, res) => {
      const [scheme, token] = (req.header("authorization") ?? "").split(" ");
      const id = scheme?.toLowerCase() === "bearer" && token ? readToken(secret, token) : undefined;
      const user = id === undefined ? undefined : await store.userById(id);
      if (!user) return void res.status(401).json({ error: "sign in first" });
      await next(req, res, user);
    };

  const adminOnly =
    (next: Handler): Handler =>
    async (req, res, user) => {
      if (!user.isAdmin) return void res.status(403).json({ error: "admins only" });
      await next(req, res, user);
    };

  const credentials = (body: unknown): { email: string; password: string } | undefined => {
    const { email, password } = (body ?? {}) as { email?: unknown; password?: unknown };
    if (typeof email !== "string" || typeof password !== "string") return undefined;
    const clean = email.trim().toLowerCase();
    if (!/^[^@\s]+@[^@\s]+$/.test(clean) || clean.length > 254 || password.length < 8 || password.length > 200) return undefined;
    return { email: clean, password };
  };

  const itemBody = (body: unknown): { name: string; done: boolean } | undefined => {
    const { name, done } = (body ?? {}) as { name?: unknown; done?: unknown };
    if (typeof name !== "string" || name.trim() === "" || name.length > 200) return undefined;
    return { name: name.trim(), done: done === true };
  };

  const itemId = (raw: unknown): number | undefined => {
    const id = typeof raw === "string" ? Number(raw) : NaN;
    return Number.isInteger(id) && id > 0 ? id : undefined;
  };

  app.get("/health", (_req, res) => {
    res.json({ status: "ok" });
  });

  app.post("/api/auth/register", async (req, res) => {
    const c = credentials(req.body);
    if (!c) return void res.status(422).json({ error: "a valid email and a password of 8 to 200 characters are required" });
    const user = await store.createUser(c.email, hashPassword(c.password));
    if (!user) return void res.status(409).json({ error: "that email is already registered" });
    res.status(201).json({ token: makeToken(secret, user.id), user: publicUser(user) });
  });

  app.post("/api/auth/login", async (req, res) => {
    const c = credentials(req.body);
    if (!c) return void res.status(422).json({ error: "a valid email and a password of 8 to 200 characters are required" });
    const user = await store.userByEmail(c.email);
    if (!user || !checkPassword(c.password, user.passwordHash)) return void res.status(401).json({ error: "wrong email or password" });
    res.json({ token: makeToken(secret, user.id), user: publicUser(user) });
  });

  app.get("/api/me", signedIn(async (_req, res, user) => void res.json(publicUser(user))));

  app.get("/api/items", signedIn(async (_req, res, user) => void res.json((await store.listItems(user.id)).map(itemJson))));

  app.post("/api/items", signedIn(async (req, res, user) => {
    const body = itemBody(req.body);
    if (!body) return void res.status(422).json({ error: "name is required (200 characters at most)" });
    res.status(201).json(itemJson(await store.createItem(user.id, body.name)));
  }));

  app.put("/api/items/:id", signedIn(async (req, res, user) => {
    const id = itemId(req.params.id);
    if (id === undefined) return void res.status(400).json({ error: "id must be a positive number" });
    const body = itemBody(req.body);
    if (!body) return void res.status(422).json({ error: "name is required (200 characters at most)" });
    const item = await store.updateItem(user.id, id, body.name, body.done);
    if (!item) return void res.status(404).json({ error: "not found" });
    res.json(itemJson(item));
  }));

  app.delete("/api/items/:id", signedIn(async (req, res, user) => {
    const id = itemId(req.params.id);
    if (id === undefined) return void res.status(400).json({ error: "id must be a positive number" });
    if (!(await store.deleteItem(user.id, id))) return void res.status(404).json({ error: "not found" });
    res.status(204).end();
  }));

  app.get("/api/admin/users", signedIn(adminOnly(async (_req, res) => void res.json((await store.listUsers()).map(publicUser)))));

  app.use((err: Error, _req: express.Request, res: express.Response, _next: express.NextFunction) => {
    const bad = err instanceof SyntaxError;
    if (!bad) console.error(err);
    res.status(bad ? 400 : 500).json({ error: bad ? "invalid JSON body" : "internal error" });
  });
  return app;
}
