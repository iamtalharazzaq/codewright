import { describe, expect, it } from "vitest";

import { addTask, removeTask, summary, toggleTask } from "./tasks";

describe("tasks", () => {
  it("adds trimmed tasks with increasing ids and ignores blank ones", () => {
    const tasks = addTask(addTask([], " Plan "), "Build");
    expect(tasks.map((t) => [t.id, t.title])).toEqual([
      [1, "Plan"],
      [2, "Build"],
    ]);
    expect(addTask(tasks, "   ")).toBe(tasks);
  });

  it("toggles, removes and summarises", () => {
    let tasks = addTask(addTask([], "a"), "b");
    tasks = toggleTask(tasks, 1);
    expect(summary(tasks)).toBe("1 of 2 left");
    tasks = removeTask(tasks, 2);
    expect(summary(tasks)).toBe("All done!");
    expect(summary([])).toBe("Nothing to do yet.");
  });
});
