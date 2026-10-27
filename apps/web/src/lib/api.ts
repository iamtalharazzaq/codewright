// Typed client for the Codewright API. All calls go through the `/api` rewrite (next.config.ts).

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
  number: number | null;
  title: string;
  question: string;
  subject: string | null;
  playbook: string;
  tier: number;
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

export interface BudgetPrompt {
  kind: "budget_exceeded";
  step: string;
  reason: string;
  used: Record<string, unknown>;
  options: Array<"continue" | "stop">;
}

export type Pending = GatePrompt | LLMUnavailablePrompt | BudgetPrompt;
export type Choice = "retry" | "switch_to_cpu" | "continue" | "stop";

export interface PlanItem {
  id: string;
  title: string;
  role: string;
  status: "pending" | "in_progress" | "done";
}

export interface ArtifactRef {
  kind: "plan" | "diff" | "graph" | "diagram" | "tests" | "preview" | "report" | "file";
  title: string;
  path: string;
  step: string;
}

export interface BudgetState {
  run: { llm_calls: number; tokens: number };
  steps: Record<string, { llm_calls: number; tokens: number }>;
  extensions: number;
}

export interface Playbook {
  name: string;
  title: string;
  description: string;
  intent: string | null;
  lead_role: string;
  tier: number;
  steps: Array<{ id: string; title: string; role: string; number: number | null }>;
  gates: Array<{
    id: string;
    title: string;
    kind: "plan" | "result" | "custom";
    number: number | null;
    reworks: string;
  }>;
  inputs_schema: Record<string, unknown>;
}

export interface Run {
  id: string;
  project_id: string | null;
  playbook: string;
  tier: 0 | 1 | 2 | 3;
  status: RunStatus;
  llm_profile: ProfileName;
  inputs: Record<string, unknown>;
  current_step: string | null;
  pending: Pending | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface RunDetail extends Run {
  usage: { prompt_tokens: number; completion_tokens: number; llm_calls: number; llm_time_ms: number };
  approvals: Array<{ gate: string; subject: string | null; decision: Decision; comment: string; at: string }>;
  flow: string[];
  plan: PlanItem[];
  steps: Record<string, { status?: string; summary?: string; subject?: string }>;
  artifacts: ArtifactRef[];
  budget: BudgetState | null;
}

export interface RunEvent {
  id: number;
  run_id: string;
  type: string;
  step: string | null;
  data: Record<string, unknown>;
  created_at: string;
}

/** A live-only LLM token (not stored, not replayed on reconnect). */
export interface TokenEvent {
  agent: string;
  node: string | null;
  text: string;
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
  if (res.status === 204) return undefined as T;
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

export const listPlaybooks = (signal?: AbortSignal) => request<Playbook[]>("GET", "/playbooks", undefined, signal);
export const getPlaybook = (name: string, signal?: AbortSignal) =>
  request<Playbook>("GET", `/playbooks/${encodeURIComponent(name)}`, undefined, signal);
export const listRuns = (signal?: AbortSignal) => request<Run[]>("GET", "/runs", undefined, signal);
export const getRun = (id: string, signal?: AbortSignal) => request<RunDetail>("GET", `/runs/${id}`, undefined, signal);
export const createRun = (body: {
  playbook: string;
  inputs: Record<string, unknown>;
  project_name?: string;
  llm_profile?: ProfileName;
  tier?: number;
}) => request<Run>("POST", "/runs", body);
export const answerRun = (id: string, body: { decision?: Decision; comment?: string; choice?: Choice }) =>
  request<{ status: string }>("POST", `/runs/${id}/answer`, body);
export const cancelRun = (id: string) => request<{ status: string }>("POST", `/runs/${id}/cancel`);
export const listTraces = (runId: string, signal?: AbortSignal) =>
  request<Trace[]>("GET", `/traces?run_id=${encodeURIComponent(runId)}`, undefined, signal);

export const PROFILE_LABEL: Record<ProfileName, string> = { remote_gpu: "Remote GPU", local_cpu: "Local CPU" };

// ── Chat (CODEWRIGHT.md Sections 2.2 and 3) ─────────────────────────────────

export interface Conversation {
  id: string;
  title: string;
  pinned: boolean;
  project_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface Question {
  question: string;
  default: string;
  options: string[];
  hint?: string;
}

export interface ConfirmCardData {
  what: string;
  stack: string;
  features: string[];
  deliver: string;
}

export type MessageKind = "text" | "questions" | "confirm" | "run" | "done" | "decline" | "error";

export interface ChatMessage {
  id: string;
  conversation_id: string;
  parent_id: string | null;
  role: "user" | "assistant";
  kind: MessageKind;
  content: string;
  data: {
    intent?: string | null;
    label?: string;
    questions?: Question[];
    card?: ConfirmCardData;
    state?: "open" | "started" | "changing" | "changed" | "replaced";
    summary?: string;
    changed?: string[];
    proof?: string[];
    guide?: string | null;
    suggestions?: string[];
    [key: string]: unknown;
  };
  status: "complete" | "streaming" | "stopped" | "error";
  run_id: string | null;
  created_at: string;
  siblings: string[];
}

export interface ConversationDetail {
  conversation: Conversation;
  messages: ChatMessage[];
  busy: boolean;
}

export interface SendResult {
  conversation: Conversation;
  user: ChatMessage;
  reply: ChatMessage;
}

export interface SlashCommand {
  command: string;
  intent: string;
  description: string;
}

export const listConversations = (q?: string, signal?: AbortSignal) =>
  request<Conversation[]>("GET", q ? `/conversations?q=${encodeURIComponent(q)}` : "/conversations", undefined, signal);
export const getConversation = (id: string, signal?: AbortSignal) =>
  request<ConversationDetail>("GET", `/conversations/${id}`, undefined, signal);
export const startConversation = (content: string) => request<SendResult>("POST", "/conversations", { content });
export const sendMessage = (id: string, content: string, editOf?: string) =>
  request<SendResult>("POST", `/conversations/${id}/messages`, { content, edit_of: editOf });
export const patchConversation = (id: string, body: { title?: string; pinned?: boolean }) =>
  request<Conversation>("PATCH", `/conversations/${id}`, body);
export const deleteConversation = (id: string) => request<void>("DELETE", `/conversations/${id}`);
export const stopConversation = (id: string) => request<void>("POST", `/conversations/${id}/stop`);
export const regenerateMessage = (id: string, messageId: string) =>
  request<ChatMessage>("POST", `/conversations/${id}/messages/${messageId}/regenerate`);
export const switchBranch = (id: string, messageId: string) =>
  request<void>("POST", `/conversations/${id}/messages/${messageId}/switch`);
export const answerConfirm = (id: string, messageId: string, choice: "start" | "change") =>
  request<ChatMessage | null>("POST", `/conversations/${id}/messages/${messageId}/confirm`, { choice });
export const listCommands = (signal?: AbortSignal) => request<SlashCommand[]>("GET", "/commands", undefined, signal);

/** Tells the sidebar's chat list to reload (a chat was created, renamed, pinned or deleted). */
export const CONVERSATIONS_CHANGED = "codewright:conversations-changed";
export const notifyConversationsChanged = () => window.dispatchEvent(new Event(CONVERSATIONS_CHANGED));
