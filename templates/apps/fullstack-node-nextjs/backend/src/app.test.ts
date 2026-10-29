import request from "supertest";
import { describe, expect, it } from "vitest";
import { createApp } from "./app.js";
import { makeToken, readToken } from "./security.js";
import { MemoryStore } from "./store.js";

const app = () => createApp(new MemoryStore(), "test-secret");

async function signUp(a: ReturnType<typeof app>, email: string): Promise<string> {
  const res = await request(a).post("/api/auth/register").send({ email, password: "password123" });
  expect(res.status).toBe(201);
  return `Bearer ${res.body.token}`;
}

describe("api", () => {
  it("answers /health", async () => {
    expect((await request(app()).get("/health")).body).toEqual({ status: "ok" });
  });

  it("registers, logs in and knows who you are", async () => {
    const a = app();
    const auth = await signUp(a, "Ada@example.com");
    expect((await request(a).get("/api/me").set("Authorization", auth)).body.email).toBe("ada@example.com");
    expect((await request(a).post("/api/auth/login").send({ email: "ada@example.com", password: "password123" })).status).toBe(200);
    expect((await request(a).post("/api/auth/login").send({ email: "ada@example.com", password: "wrong-password" })).status).toBe(401);
    expect((await request(a).post("/api/auth/register").send({ email: "ada@example.com", password: "password123" })).status).toBe(409);
  });

  it("keeps items private to their owner", async () => {
    const a = app();
    expect((await request(a).get("/api/items")).status).toBe(401);
    const ada = await signUp(a, "ada@example.com");
    const bob = await signUp(a, "bob@example.com");
    const created = await request(a).post("/api/items").set("Authorization", ada).send({ name: " Buy milk " });
    expect(created.status).toBe(201);
    expect(created.body.name).toBe("Buy milk");
    expect((await request(a).get("/api/items").set("Authorization", bob)).body).toEqual([]);
    expect((await request(a).put("/api/items/1").set("Authorization", bob).send({ name: "x" })).status).toBe(404);
    expect((await request(a).put("/api/items/1").set("Authorization", ada).send({ name: "Buy milk", done: true })).body.done).toBe(true);
    expect((await request(a).delete("/api/items/1").set("Authorization", bob)).status).toBe(404);
    expect((await request(a).delete("/api/items/1").set("Authorization", ada)).status).toBe(204);
    expect((await request(a).post("/api/items").set("Authorization", ada).send({ name: "" })).status).toBe(422);
  });

  it("lets only the first user see all users", async () => {
    const a = app();
    const ada = await signUp(a, "ada@example.com");
    const bob = await signUp(a, "bob@example.com");
    expect((await request(a).get("/api/admin/users").set("Authorization", ada)).body).toHaveLength(2);
    expect((await request(a).get("/api/admin/users").set("Authorization", bob)).status).toBe(403);
  });
});

describe("tokens", () => {
  it("expire and cannot be forged", () => {
    const token = makeToken("s3cret", 7, 1000);
    expect(readToken("s3cret", token, 1001)).toBe(7);
    expect(readToken("s3cret", token, 1000 + 8 * 24 * 3600)).toBeUndefined();
    expect(readToken("other", token, 1001)).toBeUndefined();
    expect(readToken("s3cret", "garbage")).toBeUndefined();
  });
});
