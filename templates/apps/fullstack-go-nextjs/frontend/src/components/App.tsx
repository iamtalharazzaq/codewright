"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";
import { createClient, type Item, type User } from "../lib/api";

const KEY = "token";

function readToken(): string | null {
  try {
    return window.localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

function writeToken(token: string | null): void {
  try {
    if (token) window.localStorage.setItem(KEY, token);
    else window.localStorage.removeItem(KEY);
  } catch {
    // private windows can block storage: the session then lasts until the page closes
  }
}

export function App() {
  const [token, setToken] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [user, setUser] = useState<User | null>(null);
  const [items, setItems] = useState<Item[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [error, setError] = useState("");
  const [registering, setRegistering] = useState(false);
  const api = useMemo(() => createClient(() => token), [token]);

  useEffect(() => {
    setToken(readToken());
    setReady(true);
  }, []);

  useEffect(() => {
    if (!token) {
      setUser(null);
      return;
    }
    api
      .me()
      .then(async (me) => {
        setUser(me);
        setItems(await api.listItems());
        if (me.is_admin) setUsers(await api.listUsers());
      })
      .catch(() => signOut());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  function signOut() {
    writeToken(null);
    setToken(null);
    setItems([]);
    setUsers([]);
  }

  async function run(action: () => Promise<void>) {
    setError("");
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : "something went wrong");
    }
  }

  function submitAuth(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const email = String(form.get("email"));
    const password = String(form.get("password"));
    void run(async () => {
      const session = await (registering ? api.register(email, password) : api.login(email, password));
      writeToken(session.token);
      setToken(session.token);
    });
  }

  function addItem(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const input = e.currentTarget.elements.namedItem("name") as HTMLInputElement;
    const name = input.value.trim();
    if (!name) return;
    void run(async () => {
      const item = await api.createItem(name);
      setItems((all) => [...all, item]);
      input.value = "";
    });
  }

  if (!ready) return null;

  if (!token || !user) {
    return (
      <main>
        <h1>{"{{title}}"}</h1>
        <p className="muted">{registering ? "Create an account" : "Sign in"} to continue.</p>
        <form onSubmit={submitAuth} aria-label={registering ? "Register" : "Sign in"}>
          <input name="email" type="email" placeholder="Email" aria-label="Email" required autoComplete="email" />
          <input name="password" type="password" placeholder="Password (8+ characters)" aria-label="Password"
            required minLength={8} autoComplete={registering ? "new-password" : "current-password"} />
          <button type="submit">{registering ? "Register" : "Sign in"}</button>
        </form>
        {error && <p role="alert" className="error">{error}</p>}
        <button className="link" onClick={() => setRegistering(!registering)}>
          {registering ? "I already have an account" : "Create an account"}
        </button>
      </main>
    );
  }

  return (
    <main>
      <h1>{"{{title}}"}</h1>
      <p className="muted">
        Signed in as {user.email}{user.is_admin ? " (admin)" : ""}.{" "}
        <button className="link" onClick={signOut}>Sign out</button>
      </p>
      <form onSubmit={addItem} aria-label="Add an item">
        <input name="name" placeholder="What needs doing?" aria-label="New item" maxLength={200} />
        <button type="submit">Add</button>
      </form>
      {error && <p role="alert" className="error">{error}</p>}
      <ul aria-label="Items">
        {items.map((item) => (
          <li key={item.id} className={item.done ? "done" : ""}>
            <input type="checkbox" checked={item.done} aria-label={`Done: ${item.name}`}
              onChange={() => void run(async () => {
                const saved = await api.updateItem({ ...item, done: !item.done });
                setItems((all) => all.map((i) => (i.id === saved.id ? saved : i)));
              })} />
            <span>{item.name}</span>
            <button className="danger" aria-label={`Delete ${item.name}`}
              onClick={() => void run(async () => {
                await api.deleteItem(item.id);
                setItems((all) => all.filter((i) => i.id !== item.id));
              })}>Delete</button>
          </li>
        ))}
      </ul>
      {items.length === 0 && <p className="muted">Nothing here yet.</p>}
      {user.is_admin && (
        <section aria-label="Admin">
          <h2>Users</h2>
          <ul>
            {users.map((u) => (
              <li key={u.id}><span>{u.email}</span>{u.is_admin && <span className="muted">admin</span>}</li>
            ))}
          </ul>
        </section>
      )}
    </main>
  );
}
