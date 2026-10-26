// Typed client for the MonoShift API. All calls go through the `/api` rewrite (next.config.ts).

export type ProjectMode = "conversion" | "audit";

export interface Project {
  id: string;
  name: string;
  mode: ProjectMode;
  status: string;
  created_at: string;
  updated_at: string;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function getJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: { Accept: "application/json", ...init?.headers },
  });
  if (!res.ok) {
    throw new ApiError(`GET ${path} failed with ${res.status}`, res.status);
  }
  return (await res.json()) as T;
}

export function listProjects(signal?: AbortSignal): Promise<Project[]> {
  return getJson<Project[]>("/projects", { signal });
}
