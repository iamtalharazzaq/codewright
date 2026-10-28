import { useState } from "react";

import { addTask, removeTask, summary, toggleTask, type Task } from "./lib/tasks";

type Theme = "light" | "dark";

export function App() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [title, setTitle] = useState("");
  const [theme, setTheme] = useState<Theme>(() =>
    window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light",
  );
  document.documentElement.dataset.theme = theme;

  return (
    <main>
      <header>
        <div>
          <h1>{{title}}</h1>
          <p>{{description}}</p>
        </div>
        <button className="ghost" onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>
          {theme === "dark" ? "Light" : "Dark"} mode
        </button>
      </header>
      <section className="card" aria-label="Tasks">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            setTasks((t) => addTask(t, title));
            setTitle("");
          }}
        >
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Add a task" aria-label="New task" />
          <button type="submit">Add</button>
        </form>
        <ul>
          {tasks.map((t) => (
            <li key={t.id} className={t.done ? "done" : ""}>
              <input
                type="checkbox"
                checked={t.done}
                onChange={() => setTasks((all) => toggleTask(all, t.id))}
                aria-label={`Done: ${t.title}`}
              />
              <span>{t.title}</span>
              <button className="ghost" onClick={() => setTasks((all) => removeTask(all, t.id))} aria-label={`Remove ${t.title}`}>
                ×
              </button>
            </li>
          ))}
        </ul>
        <p role="status">{summary(tasks)}</p>
      </section>
    </main>
  );
}
