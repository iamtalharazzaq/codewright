import { describe, expect, it } from "vitest";
import { ApiError, createClient } from "./api";

function fakeFetch(status: number, body: unknown) {
  const calls: { url: string; init?: RequestInit }[] = [];
  const impl = async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    return new Response(status === 204 ? null : JSON.stringify(body), { status });
  };
  return { impl, calls };
}

describe("api client", () => {
  it("sends the token and parses the answer", async () => {
    const { impl, calls } = fakeFetch(200, [{ id: 1, name: "milk", done: false }]);
    const items = await createClient(() => "abc", impl).listItems();
    expect(items).toHaveLength(1);
    expect(calls[0].url).toBe("/api/items");
    expect((calls[0].init?.headers as Record<string, string>).Authorization).toBe("Bearer abc");
  });

  it("sends JSON bodies without a token when signed out", async () => {
    const { impl, calls } = fakeFetch(201, { token: "t", user: { id: 1, email: "a@b.c", is_admin: true } });
    await createClient(() => null, impl).register("a@b.c", "password1");
    const headers = calls[0].init?.headers as Record<string, string>;
    expect(headers.Authorization).toBeUndefined();
    expect(headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({ email: "a@b.c", password: "password1" });
  });

  it("turns errors into ApiError with the server's message", async () => {
    const { impl } = fakeFetch(401, { error: "wrong email or password" });
    await expect(createClient(() => null, impl).login("a@b.c", "x")).rejects.toMatchObject({
      status: 401,
      message: "wrong email or password",
    });
    await expect(createClient(() => null, impl).login("a@b.c", "x")).rejects.toBeInstanceOf(ApiError);
  });

  it("handles 204 with no body", async () => {
    const { impl } = fakeFetch(204, null);
    await expect(createClient(() => "t", impl).deleteItem(3)).resolves.toBeUndefined();
  });
});
