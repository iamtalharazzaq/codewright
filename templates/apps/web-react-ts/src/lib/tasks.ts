// The app's logic: pure functions over plain data, so they are easy to test.

export interface Task {
  id: number;
  title: string;
  done: boolean;
}

export function addTask(tasks: Task[], title: string): Task[] {
  const clean = title.trim();
  if (!clean) return tasks;
  const id = tasks.reduce((max, t) => Math.max(max, t.id), 0) + 1;
  return [...tasks, { id, title: clean, done: false }];
}

export function toggleTask(tasks: Task[], id: number): Task[] {
  return tasks.map((t) => (t.id === id ? { ...t, done: !t.done } : t));
}

export function removeTask(tasks: Task[], id: number): Task[] {
  return tasks.filter((t) => t.id !== id);
}

export function summary(tasks: Task[]): string {
  const left = tasks.filter((t) => !t.done).length;
  if (tasks.length === 0) return "Nothing to do yet.";
  return left === 0 ? "All done!" : `${left} of ${tasks.length} left`;
}
