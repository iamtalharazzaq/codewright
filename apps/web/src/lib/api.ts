// Typed client for the Codewright API. All calls go through the `/api` rewrite (next.config.ts).

// Variant of the microservices playbook (the only playbook with a run skeleton so far).
export type MicroservicesMode = "conversion" | "audit";
export type ProfileName = "remote_gpu" | "local_cpu";
export type RunStatus = "created" | "running" | "waiting" | "completed" | "failed" | "cancelled";
export type Decision = "approve" | "edit" | "reject";

export interface Project {
  id: string;
  name: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface GatePrompt {
  kind: "gate";
  gate: string;
  number: number;
  title: string;
  question: string;
  subject: string | null;
  summary: Record<string, unknown>;
  options: Decision[];
}

export interface LLMUnavailablePrompt {
  kind: "llm_unavailable";
  step: string;
  profile: ProfileName;
  error: string;
  options: Array<"retry" | "switch_to_cpu">;
}

export type Pending = GatePrompt | LLMUnavailablePrompt;

export interface Run {
  id: string;
  project_id: string;
  playbook: string;
  tier: 0 | 1 | 2 | 3;
  mode: MicroservicesMode;
  status: RunStatus;
  llm_profile: ProfileName;
  options: { stub_delay_s?: number; use_llm?: boolean; services?: string[] };
  current_step: string | null;
  pending: Pending | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface RunDetail extends Run {
  usage: { prompt_tokens: number; completion_tokens: number; llm_calls: number; llm_time_ms: number };
  approvals: Array<{ gate: string; subject: string | null; decision: Decision; comment: string; at: string }>;
}

export interface RunEvent {
  id: number;
  run_id: string;
  type: string;
  step: string | null;
  data: Record<string, unknown>;
  created_at: string;
}

export interface Workflow {
  steps: Array<{ id: string; title: string; role: string; number: number | null }>;
  gates: Array<{ id: string; number: number; title: string; reworks: string }>;
}

export interface LLMProfileView {
  server: string;
  base_url: string | null;
  model: string;
  num_ctx: number;
  max_parallel_llm_jobs: number;
  configured: boolean;
  api_key_configured: boolean;
}

export interface SettingsView {
  active_llm_profile: ProfileName;
  llm_profiles: Record<ProfileName, LLMProfileView>;
  embeddings_model: string;
  external_llm_enabled: boolean;
}

export interface HealthView {
  profile: ProfileName;
  status: "ok" | "loading" | "unreachable" | "not_configured" | "error";
  base_url: string | null;
  latency_ms: number | null;
  server_model: string | null;
  server_ctx: number | null;
  server_slots: number | null;
  warnings: string[];
  detail: string | null;
}

export interface Trace {
  id: number;
  run_id: string | null;
  step: string | null;
  role: string | null;
  kind: string;
  name: string;
  profile: string | null;
  model: string | null;
  input: unknown;
  output: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  latency_ms: number;
  status: "ok" | "error";
  error: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
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

async function request<T>(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method,
    signal,
    headers: { Accept: "application/json", ...(body !== undefined ? { "Content-Type": "application/json" } : {}) },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let detail = `${method} ${path} failed with ${res.status}`;
    try {
      const data = (await res.json()) as { detail?: unknown };
      if (typeof data.detail === "string") detail = data.detail;
      else if (Array.isArray(data.detail)) detail = data.detail.map((d: { msg?: string }) => d.msg).join("; ");
    } catch {
      // keep the generic message
    }
    throw new ApiError(detail, res.status);
  }
  return (await res.json()) as T;
}

export const listProjects = (signal?: AbortSignal) => request<Project[]>("GET", "/projects", undefined, signal);

export const getSettings = (signal?: AbortSignal) => request<SettingsView>("GET", "/settings", undefined, signal);
export const updateLLMSettings = (body: {
  active_profile?: ProfileName;
  profiles?: Partial<Record<ProfileName, { base_url?: string; model?: string; num_ctx?: number }>>;
}) => request<SettingsView>("PUT", "/settings/llm", body);
export const checkHealth = (signal?: AbortSignal, profile?: ProfileName) =>
  request<HealthView[]>("GET", profile ? `/llm/health?profile=${profile}` : "/llm/health", undefined, signal);

export const getWorkflow = (signal?: AbortSignal) => request<Workflow>("GET", "/runs/workflow", undefined, signal);
export const listRuns = (signal?: AbortSignal) => request<Run[]>("GET", "/runs", undefined, signal);
export const getRun = (id: string, signal?: AbortSignal) => request<RunDetail>("GET", `/runs/${id}`, undefined, signal);
export const createRun = (body: {
  project_name: string;
  mode: MicroservicesMode;
  llm_profile?: ProfileName;
  options: { stub_delay_s: number; use_llm: boolean; services?: string[] };
}) => request<Run>("POST", "/runs", body);
export const answerRun = (
  id: string,
  body: { decision?: Decision; comment?: string; choice?: "retry" | "switch_to_cpu" },
) => request<{ status: string }>("POST", `/runs/${id}/answer`, body);
export const cancelRun = (id: string) => request<{ status: string }>("POST", `/runs/${id}/cancel`);
export const listTraces = (runId: string, signal?: AbortSignal) =>
  request<Trace[]>("GET", `/traces?run_id=${encodeURIComponent(runId)}`, undefined, signal);

export const PROFILE_LABEL: Record<ProfileName, string> = { remote_gpu: "Remote GPU", local_cpu: "Local CPU" };
