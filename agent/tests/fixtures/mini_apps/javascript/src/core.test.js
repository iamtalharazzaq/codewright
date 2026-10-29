import { describe, expect, it } from "vitest";
import { greet, wordCount } from "./core.js";

describe("greet", () => {
  it("greets by name", () => {
    expect(greet("Ada")).toBe("Hello, Ada!");
    expect(greet("  ")).toBe("Hello, world!");
  });
});

describe("wordCount", () => {
  it("orders by frequency", () => {
    expect(wordCount("b a b. C c c")).toEqual({ c: 3, b: 2, a: 1 });
  });
});
