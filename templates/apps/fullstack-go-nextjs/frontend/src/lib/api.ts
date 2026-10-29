export interface User {
  id: number;
  email: string;
  is_admin: boolean;
}

export interface Item {
  id: number;
  name: string;
  done: boolean;
}

export interface Session {
  token: string;
  user: User;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

type Fetch = (input: string, init?: RequestInit) => Promise<Response>;

/** A small typed client for the backend. `getToken` says which sign-in to use; `fetchImpl` is replaceable in tests. */
export function createClient(getToken: () => string | null, fetchImpl: Fetch = (i, init) => fetch(i, init)) {
  async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
    const headers: Record<string, string> = {};
    const token = getToken();
    if (token) headers.Authorization = `Bearer ${token}`;
    if (body !== undefined) headers["Content-Type"] = "application/json";
    const res = await fetchImpl(`/api${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!res.ok) {
      const detail = (await res.json().catch(() => null)) as { error?: string; detail?: string } | null;
      throw new ApiError(res.status, detail?.error ?? detail?.detail ?? res.statusText);
    }
    return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
  }

  return {
    register: (email: string, password: string) => call<Session>("POST", "/auth/register", { email, password }),
    login: (email: string, password: string) => call<Session>("POST", "/auth/login", { email, password }),
    me: () => call<User>("GET", "/me"),
    listItems: () => call<Item[]>("GET", "/items"),
    createItem: (name: string) => call<Item>("POST", "/items", { name }),
    updateItem: (item: Item) => call<Item>("PUT", `/items/${item.id}`, { name: item.name, done: item.done }),
    deleteItem: (id: number) => call<void>("DELETE", `/items/${id}`),
    listUsers: () => call<User[]>("GET", "/admin/users"),
  };
}
