import { expect, it } from "vitest";
import { add } from "./{{name_snake}}.js";

it("adds", () => expect(add(2, 3)).toBe(5));
