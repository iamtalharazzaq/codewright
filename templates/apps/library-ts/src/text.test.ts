import { describe, expect, it } from "vitest";
import { slugify, truncate } from "./index.js";

describe("slugify", () => {
  it("joins words with dashes", () => expect(slugify("Hello, World!")).toBe("hello-world"));
  it("returns an empty string for no words", () => expect(slugify("  --  ")).toBe(""));
});

describe("truncate", () => {
  it("leaves short text alone", () => expect(truncate("short", 10)).toBe("short"));
  it("cuts long text", () => expect(truncate("a longer sentence", 8)).toBe("a longe…"));
  it("rejects a tiny limit", () => expect(() => truncate("anything", 0)).toThrow(RangeError));
});
