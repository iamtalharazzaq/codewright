import request from "supertest";
import { describe, expect, it } from "vitest";
import { createApp } from "./app.js";

describe("api", () => {
  it("answers /health", async () => {
    const res = await request(createApp()).get("/health");
    expect(res.body).toEqual({ status: "ok" });
  });

  it("does a CRUD roundtrip", async () => {
    const app = createApp();
    const created = await request(app).post("/api/items").send({ name: " Buy milk " });
    expect(created.status).toBe(201);
    expect(created.body).toEqual({ id: 1, name: "Buy milk", done: false });
    const updated = await request(app).put("/api/items/1").send({ name: "Buy milk", done: true });
    expect(updated.body.done).toBe(true);
    expect((await request(app).get("/api/items")).body).toHaveLength(1);
    expect((await request(app).delete("/api/items/1")).status).toBe(204);
    expect((await request(app).get("/api/items/1")).status).toBe(404);
  });

  it("validates input", async () => {
    const app = createApp();
    expect((await request(app).post("/api/items").send({ name: "" })).status).toBe(422);
    expect((await request(app).get("/api/items/abc")).status).toBe(400);
    expect((await request(app).post("/api/items").set("Content-Type", "application/json").send("{")).status).toBe(400);
  });
});
