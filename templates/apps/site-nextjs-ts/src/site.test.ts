import { describe, expect, it } from "vitest";
import { absoluteUrl, site } from "./site";

describe("site", () => {
  it("builds absolute URLs", () => {
    expect(absoluteUrl("/about")).toBe(new URL("/about", site.url).toString());
  });

  it("links the home page first", () => {
    expect(site.nav[0].href).toBe("/");
  });

  it("has a unique path for every nav item", () => {
    const hrefs = site.nav.map((n) => n.href);
    expect(new Set(hrefs).size).toBe(hrefs.length);
  });
});
