// Typed client for the Codewright API. All calls go through the `/api` rewrite (next.config.ts).

export type ProfileName = "remote_gpu" | "local_cpu";
export type RunStatus = "created" | "running" | "waiting" | "completed" | "failed" | "cancelled";
export type Decision = "approve" | "edit" | "reject";

export type SourceKind = "zip" | "github" | "local" | "drive" | "empty";
export type DeliverTarget = "local" | "zip" | "github" | "drive" | "drive_zip";

export interface ProjectSummary {
  files?: number;
  size_bytes?: number;
  languages?: Record<string, number>;
  top_level?: string[];
}

export interface Project {
  id: string;
  name: string;
  status: string; // importing | ready | failed
  source: { kind?: SourceKind; ref?: string };
  summary: ProjectSummary;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface SecretFinding {
  kind: string;
  path: string;
  line: number;
}

export interface ProjectDetail extends Project {
  instructions: string;
  secrets: SecretFinding[];
  branch: string | null;
  chats: { id: string; title: string; updated_at: string }[];
  runs: { id: string; playbook: string; status: string }[];
  memory: { id: number; key: string; value: string }[];
  /** Set when the project is mostly in a language Codewright doesn't work in (C12). */
  unsupported: { language: string; suggestions: string[]; message: string } | null;
}

export interface Connectors {
  github_token: boolean;
  local_folders: string[];
  output_folder: boolean;
  drive: { configured: boolean; connected: boolean; problem?: string | null; email?: string | null };
}

export interface DeliveryResult {
  target: DeliverTarget | "cleanup";
  ok: boolean;
  location?: string;
  detail?: string;
  error?: string;
}

export interface UploadInfo {
  id: string;
  filename: string;
  kind: string;
  size: number;
  secrets: SecretFinding[];
}

export interface Attachment {
  id: string;
  filename: string;
  kind: string;
  secrets: number;
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
  status: "pending" | "in_progress" | "done" | "failed";
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
  steps: Record<string, { status?: "done" | "failed" | "skipped"; summary?: string; subject?: string }>;
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
      else if (data.detail && typeof data.detail === "object" && "message" in data.detail) {
        // Skill validation: {message, problems}
        const d = data.detail as { message: string; problems?: string[] };
        detail = d.problems?.length ? d.problems.join("\n") : d.message;
      }
    } catch {
      // keep the generic message
    }
    throw new ApiError(detail, res.status);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** A multipart POST (file uploads). Errors read like `request`'s. */
async function postForm<T>(path: string, form: FormData): Promise<T> {
  const res = await fetch(`/api${path}`, { method: "POST", body: form, headers: { Accept: "application/json" } });
  if (!res.ok) {
    let detail = `POST ${path} failed with ${res.status}`;
    try {
      const data = (await res.json()) as { detail?: unknown };
      if (typeof data.detail === "string") detail = data.detail;
      else if (data.detail && typeof data.detail === "object" && "message" in data.detail) {
        const d = data.detail as { message: string; problems?: string[] };
        detail = d.problems?.length ? d.problems.join("\n") : d.message;
      }
    } catch {
      // keep the generic message
    }
    throw new ApiError(detail, res.status);
  }
  return (await res.json()) as T;
}

export const listProjects = (signal?: AbortSignal) => request<Project[]>("GET", "/projects", undefined, signal);
export const getProject = (id: string, signal?: AbortSignal) =>
  request<ProjectDetail>("GET", `/projects/${id}`, undefined, signal);
export function createProject(body: { kind: SourceKind; name?: string; ref?: string; file?: File }) {
  const form = new FormData();
  form.set("kind", body.kind);
  if (body.name) form.set("name", body.name);
  if (body.ref) form.set("ref", body.ref);
  if (body.file) form.set("file", body.file);
  return postForm<Project>("/projects", form);
}
export const patchProject = (id: string, body: { name?: string; instructions?: string }) =>
  request<Project>("PATCH", `/projects/${id}`, body);
export const deleteProject = (id: string) => request<void>("DELETE", `/projects/${id}`);
export const addMemory = (id: string, key: string, value: string) =>
  request<{ id: number }>("POST", `/projects/${id}/memory`, { key, value });
export const deleteMemory = (id: string, itemId: number) => request<void>("DELETE", `/projects/${id}/memory/${itemId}`);
export const getConnectors = (signal?: AbortSignal) => request<Connectors>("GET", "/connectors", undefined, signal);
export const deliver = (body: {
  targets: DeliverTarget[];
  project_id?: string;
  run_id?: string;
  github_repo?: string;
  remove_local?: boolean;
}) => request<DeliveryResult[]>("POST", "/deliver", body);
export const disconnectDrive = () => request<void>("DELETE", "/connectors/gdrive");
export function uploadFile(file: File) {
  const form = new FormData();
  form.set("file", file);
  return postForm<UploadInfo>("/uploads", form);
}
export interface GraphModule {
  id: string;
  label: string;
  files: string[];
  file_count: number;
  symbols: number;
  languages: Record<string, number>;
}

export interface GraphEdge {
  source: string;
  target: string;
  weight: number;
  relations: Record<string, number>;
  sources: { source: string; confidence: string | number; commits?: number; note?: string }[];
  /** Added or confirmed by the user (USER_FACT). */
  user_fact?: boolean;
  /** The user said this link doesn't exist; kept so it can be seen. */
  disputed?: boolean;
}

export interface GraphDiff {
  added: string[];
  changed: string[];
  removed: string[];
  edges_added: string[];
  edges_removed: string[];
}

export interface GraphVersion {
  number: number;
  created_at: number;
  reason: string;
  nodes: number;
  edges: number;
  modules: number;
  diff: GraphDiff;
  hygiene: {
    code_files: number;
    files_without_symbols: string[];
    isolated_modules: string[];
    mutual_dependencies: string[];
  };
}

export interface ProjectGraph {
  versions: GraphVersion[];
  version: number | null;
  graph: { nodes: GraphModule[]; edges: GraphEdge[] } | null;
  building: boolean;
}

export interface SearchHit {
  path: string;
  start_line: number;
  end_line: number;
  content: string;
  score: number;
  match: "semantic" | "keyword";
}

export const getGraph = (id: string, version?: number | null, signal?: AbortSignal) =>
  request<ProjectGraph>("GET", `/projects/${id}/graph${version ? `?version=${version}` : ""}`, undefined, signal);
export const refreshGraph = (id: string) => request<{ queued: boolean }>("POST", `/projects/${id}/graph`, {});
export const searchCode = (id: string, q: string) =>
  request<SearchHit[]>("GET", `/projects/${id}/search?q=${encodeURIComponent(q)}`);

export const PROJECTS_CHANGED = "codewright:projects-changed";
export const notifyProjectsChanged = () => window.dispatchEvent(new Event(PROJECTS_CHANGED));

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
  /** Tick-boxes: any number of the options; the answer is a comma list. */
  multi?: boolean;
}

export interface ConfirmCardData {
  what: string;
  stack: string;
  features: string[];
  deliver: string;
}

export type MessageKind =
  "text" | "questions" | "confirm" | "run" | "done" | "decline" | "error" | "correction" | "skill_draft";

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
    attachments?: Attachment[];
    summary?: string;
    changed?: string[];
    proof?: string[];
    guide?: string | null;
    suggestions?: string[];
    playbook?: string;
    /** A new app that can be opened in the Preview tab (false for a plain function or library). */
    viewable?: boolean;
    /** A "done" message's own honest pass/fail (a step may have failed even though the run reached "completed"). */
    passed?: boolean;
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
  title?: string;
  source?: SkillSource;
}

/** The skill a reply used (Section 8.6): shown as "Using skill: …" with "Run without it" when picked automatically. */
export interface SkillRef {
  name: string;
  title: string;
  command: string;
  source?: SkillSource;
  auto?: boolean;
}

/** A diagram drawn from an explanation, for the Diagram tab. */
export interface DiagramData {
  title: string;
  kind: "sequence" | "flowchart";
  mermaid: string;
}

export interface GraphFact {
  source: string;
  target: string;
  relation: "calls" | "uses" | "depends_on" | "not_calls";
  note: string;
  at?: number;
}

export const listConversations = (q?: string, signal?: AbortSignal) =>
  request<Conversation[]>("GET", q ? `/conversations?q=${encodeURIComponent(q)}` : "/conversations", undefined, signal);
export const getConversation = (id: string, signal?: AbortSignal) =>
  request<ConversationDetail>("GET", `/conversations/${id}`, undefined, signal);
export const startConversation = (content: string, projectId?: string | null, attachments: string[] = []) =>
  request<SendResult>("POST", "/conversations", { content, project_id: projectId ?? null, attachments });
export const sendMessage = (id: string, content: string, editOf?: string, attachments: string[] = []) =>
  request<SendResult>("POST", `/conversations/${id}/messages`, { content, edit_of: editOf, attachments });
export const patchConversation = (id: string, body: { title?: string; pinned?: boolean }) =>
  request<Conversation>("PATCH", `/conversations/${id}`, body);
export const deleteConversation = (id: string) => request<void>("DELETE", `/conversations/${id}`);
export const stopConversation = (id: string) => request<void>("POST", `/conversations/${id}/stop`);
export const regenerateMessage = (id: string, messageId: string, withoutSkill = false) =>
  request<ChatMessage>(
    "POST",
    `/conversations/${id}/messages/${messageId}/regenerate`,
    withoutSkill ? { without_skill: true } : undefined,
  );
export const resolveCard = (
  id: string,
  messageId: string,
  body: { action: "save" | "discard"; markdown?: string; project_id?: string | null },
) => request<ChatMessage>("POST", `/conversations/${id}/messages/${messageId}/resolve`, body);
export const switchBranch = (id: string, messageId: string) =>
  request<void>("POST", `/conversations/${id}/messages/${messageId}/switch`);
export const answerConfirm = (id: string, messageId: string, choice: "start" | "change") =>
  request<ChatMessage | null>("POST", `/conversations/${id}/messages/${messageId}/confirm`, { choice });
export const listCommands = (projectId?: string | null, signal?: AbortSignal) =>
  request<SlashCommand[]>("GET", projectId ? `/commands?project_id=${projectId}` : "/commands", undefined, signal);

/** Tells the sidebar's chat list to reload (a chat was created, renamed, pinned or deleted). */
export const CONVERSATIONS_CHANGED = "codewright:conversations-changed";
export const notifyConversationsChanged = () => window.dispatchEvent(new Event(CONVERSATIONS_CHANGED));

// ── Sandbox (Phase 5, ADR 0020) ─────────────────────────────────────────────
export type SandboxAction = "build" | "test" | "lint" | "run";

export interface SandboxComponent {
  pack: string;
  path: string;
  kind: string;
  frameworks: string[];
  entrypoints: string[];
  manifest: string;
  run: { kind: "web" | "terminal"; cmd: string[]; port: number | null; services: string[] } | null;
}

export interface Preview {
  id: string;
  session: string;
  kind: "web" | "terminal";
  name: string;
  cmd: string[];
  port: number | null;
  url: string | null;
  running: boolean;
  exit_code: number | null;
  started_at: number;
  component?: string;
}

export interface TestCaseResult {
  name: string;
  status: "passed" | "failed" | "skipped" | "error";
  message: string;
  file: string;
}

export interface FileCoverage {
  file: string;
  covered: number;
  total: number;
  percent: number;
}

export interface Coverage {
  tool: string;
  covered: number;
  total: number;
  percent: number;
  files: FileCoverage[];
}

export interface TestReport {
  tool: string;
  passed: number;
  failed: number;
  skipped: number;
  errors: number;
  total: number;
  ok: boolean;
  found: boolean;
  cases: TestCaseResult[];
  coverage: Coverage | null;
}

export interface StepResult {
  step: string;
  exit_code: number;
  duration_s: number;
  output_tail: string;
  timed_out: boolean;
  oom_killed: boolean;
  ok: boolean;
}

export interface ActionResult {
  action: SandboxAction;
  component: string;
  pack: string;
  ok: boolean;
  steps: StepResult[];
  report: TestReport | null;
  error: string | null;
  duration_s: number;
}

export interface SandboxActivity {
  id: string;
  action: SandboxAction;
  components: string[];
  status: "running" | "passed" | "failed" | "error";
  started_at: number;
  finished_at: number | null;
  results: ActionResult[];
  previews: Preview[];
  error: string | null;
}

export interface SandboxStatus {
  runner: { docker?: boolean; gateway?: boolean; images?: Record<string, boolean>; error?: string } | null;
  components: SandboxComponent[];
  session: { id: string; services: string[]; previews: Preview[] } | null;
  activities: SandboxActivity[];
}

export const getSandbox = (id: string, signal?: AbortSignal) =>
  request<SandboxStatus>("GET", `/projects/${id}/sandbox`, undefined, signal);
export const startSandboxAction = (id: string, action: SandboxAction, components: string[] = []) =>
  request<SandboxActivity>("POST", `/projects/${id}/sandbox/actions`, { action, components });
export const stopSandbox = (id: string) => request<void>("DELETE", `/projects/${id}/sandbox`);
export const stopPreview = (id: string, previewId: string) =>
  request<void>("DELETE", `/projects/${id}/sandbox/previews/${previewId}`);
export const sendPreviewInput = (id: string, previewId: string, data: string) =>
  request<void>("POST", `/projects/${id}/sandbox/previews/${previewId}/input`, { data });
export const resizePreview = (id: string, previewId: string, rows: number, cols: number) =>
  request<void>("POST", `/projects/${id}/sandbox/previews/${previewId}/resize`, { rows, cols });
export const activityEventsUrl = (id: string, activityId: string) =>
  `/api/projects/${id}/sandbox/actions/${activityId}/events`;
export const previewOutputUrl = (id: string, previewId: string) =>
  `/api/projects/${id}/sandbox/previews/${previewId}/output`;

// ── Verification (Phase 7, ADR 0022) ────────────────────────────────────────
export type VerifyAction = "test" | "characterize" | "record" | "record-live" | "replay" | "bench" | "screens";
export type Verdict = "regression" | "noise" | "intended";

export interface NoiseRule {
  id: string;
  kind: "ignore" | "id" | "timestamp" | "token" | "tolerance" | "unordered";
  description: string;
  where: string;
  tolerance: number;
  enabled: boolean;
  builtin: boolean;
}

export interface ReportSummary {
  id: string;
  kind: "replay" | "record" | "tests" | "bench" | "screens";
  started_at: number;
  duration_s?: number;
  ok: boolean;
  counts?: { exchanges: number; regression: number; noise: number; intended: number; identical: number };
  noise_used?: Record<string, number>;
  recording?: string;
  target?: { component?: string; pack?: string };
  exchanges?: number;
  endpoints?: number;
  journeys?: string[];
  server_errors?: number;
  unanswered?: number;
  summary?: {
    passed?: number;
    failed?: number;
    skipped?: number;
    errors?: number;
    coverage?: number | null;
    // bench
    requests?: number;
    rps?: number;
    failed_rate?: number;
    p95_ms?: number | null;
    // screens
    pages?: number;
    changed?: number;
    baseline?: string;
  };
  comparison?: BenchComparison | null;
}

export interface BenchDelta {
  before: number | null;
  after: number | null;
  change_pct: number | null;
}

export interface BenchComparison {
  p95_ms: BenchDelta;
  rps: BenchDelta;
  endpoints: ({ endpoint: string } & BenchDelta)[];
}

export interface BenchReport extends ReportSummary {
  kind: "bench";
  settings: { vus: number; duration_s: number; endpoints: string[] };
  summary: {
    requests: number;
    rps: number;
    failed_rate: number;
    avg_ms: number | null;
    med_ms: number | null;
    p95_ms: number | null;
    p99_ms: number | null;
    endpoints: { endpoint: string; avg_ms: number | null; p95_ms: number | null; max_ms: number | null }[];
  };
  compared_with: string | null;
}

export interface ScreensReport extends ReportSummary {
  kind: "screens";
  pages: {
    path: string;
    file: string;
    status?: number | null;
    diff_ratio?: number;
    diff_file?: string;
    error?: string;
  }[];
}

export interface Difference {
  where: string;
  path: string;
  before: unknown;
  after: unknown;
  verdict: Verdict;
  rule: string | null;
  note: string;
}

export interface ReplayedExchange {
  seq: number;
  journey: string;
  step: string;
  method: string;
  path: string;
  status_before: number | null;
  status_after: number | null;
  duration_before_ms: number;
  duration_after_ms: number;
  differences: Difference[];
  regressions: number;
  error: string;
}

export interface ReplayReport extends ReportSummary {
  kind: "replay";
  base_url: string;
  results: ReplayedExchange[];
  rules: NoiseRule[];
  notes: string[];
}

export interface TestsReport extends ReportSummary {
  kind: "tests";
  components: {
    path: string;
    pack: string;
    ok: boolean;
    error: string | null;
    duration_s: number | null;
    report: TestReport | Record<string, never>;
    failed_step: string | null;
  }[];
  error: string | null;
}

export interface RecordingSummary {
  id: string;
  source: "journeys" | "recorder" | "har";
  target: { component?: string; pack?: string };
  created_at: number;
  exchanges: number;
  endpoints: number;
  journeys: string[];
  server_errors: number;
  unanswered: number;
  notes: string[];
}

export interface VerificationActivity {
  id: string;
  action: VerifyAction;
  components: string[];
  status: "running" | "passed" | "failed" | "error";
  started_at: number;
  finished_at: number | null;
  results: ReportSummary[];
  error: string | null;
}

export interface VerificationStatus {
  recordings: RecordingSummary[];
  reports: ReportSummary[];
  journeys: { name: string; source: string; about: string; steps: number }[];
  rules: NoiseRule[];
  activities: VerificationActivity[];
  running: boolean;
}

export const getVerification = (id: string, signal?: AbortSignal) =>
  request<VerificationStatus>("GET", `/projects/${id}/verification`, undefined, signal);
export const startVerification = (id: string, action: VerifyAction, options: Record<string, unknown> = {}) =>
  request<VerificationActivity>("POST", `/projects/${id}/verification/actions`, { action, ...options });
export const getVerificationReport = <T extends ReportSummary = ReportSummary>(id: string, reportId: string) =>
  request<T>("GET", `/projects/${id}/verification/reports/${reportId}`);
export const setNoiseRules = (id: string, enabled: Record<string, boolean>, rules: NoiseRule[] = []) =>
  request<NoiseRule[]>("PUT", `/projects/${id}/verification/noise`, { enabled, rules });
export const stopRecorder = (id: string) =>
  request<{ stopping: boolean }>("POST", `/projects/${id}/verification/recorder/stop`);
export const importHar = (id: string, har: unknown) =>
  request<RecordingSummary>("POST", `/projects/${id}/verification/recordings/har`, har);
export const screenshotUrl = (id: string, run: string, file: string) =>
  `/api/projects/${id}/verification/screens/${run}/${file}`;
export const verificationEventsUrl = (id: string, activityId: string) =>
  `/api/projects/${id}/verification/actions/${activityId}/events`;

// ── Skills (Phase 6, ADR 0021) ──────────────────────────────────────────────
export type SkillSource = "builtin" | "user" | "project";

export interface Skill {
  name: string;
  command: string;
  title: string;
  description: string;
  languages: string[];
  scope: string;
  playbook: string;
  intent_label: string;
  tier: number;
  inputs: { name: string; required: boolean; description: string }[];
  allowed_tools: string[];
  output: string;
  enabled: boolean;
  auto_use: boolean;
  instructions: string;
  source: SkillSource;
  editable: boolean;
  files: string[];
  markdown: string;
}

export interface ImportResult {
  folder: string;
  ok: boolean;
  problems?: string[];
  name?: string;
  command?: string;
  description?: string;
  allowed_tools?: string[];
  playbook?: string;
  instructions_preview?: string;
  replaced?: boolean;
}

const scopeQuery = (projectId?: string | null) => (projectId ? `?project_id=${projectId}` : "");

export const listSkills = (projectId?: string | null, signal?: AbortSignal) =>
  request<Skill[]>("GET", `/skills${scopeQuery(projectId)}`, undefined, signal);
export const getSkillTemplate = () => request<{ markdown: string; tools: string[] }>("GET", "/skills/template");
export const createSkill = (markdown: string, projectId?: string | null) =>
  request<Skill>("POST", "/skills", { markdown, project_id: projectId ?? null });
export const replaceSkill = (name: string, markdown: string, projectId?: string | null) =>
  request<Skill>("PUT", `/skills/${encodeURIComponent(name)}`, { markdown, project_id: projectId ?? null });
export const setSkillFlags = (
  name: string,
  flags: { enabled?: boolean; auto_use?: boolean },
  projectId?: string | null,
) => request<Skill>("PATCH", `/skills/${encodeURIComponent(name)}${scopeQuery(projectId)}`, flags);
export const deleteSkill = (name: string, projectId?: string | null) =>
  request<void>("DELETE", `/skills/${encodeURIComponent(name)}${scopeQuery(projectId)}`);
export const skillExportUrl = (name: string, projectId?: string | null) =>
  `/api/skills/${encodeURIComponent(name)}/export${scopeQuery(projectId)}`;
export const trySkill = (name: string, input: string, projectId?: string | null) =>
  request<{ conversation_id: string }>("POST", `/skills/${encodeURIComponent(name)}/try`, {
    input,
    project_id: projectId ?? null,
  });
export const importSkills = (source: { file?: File; gitUrl?: string; folder?: string }, projectId?: string | null) => {
  const form = new FormData();
  if (source.file) form.append("file", source.file);
  if (source.gitUrl) form.append("git_url", source.gitUrl);
  if (source.folder) form.append("folder", source.folder);
  if (projectId) form.append("project_id", projectId);
  return postForm<{ results: ImportResult[]; imported: number }>("/skills/import", form);
};

// ── Run artifacts and graph facts (Phase 6) ─────────────────────────────────
export async function getRunArtifact(runId: string, path: string, signal?: AbortSignal): Promise<string> {
  const res = await fetch(`/api/runs/${runId}/artifact?path=${encodeURIComponent(path)}`, { signal });
  if (!res.ok) throw new ApiError(`Couldn't load ${path} (${res.status})`, res.status);
  return res.text();
}
export const listFacts = (projectId: string, signal?: AbortSignal) =>
  request<GraphFact[]>("GET", `/projects/${projectId}/graph/facts`, undefined, signal);
export const removeFact = (projectId: string, source: string, target: string) =>
  request<void>(
    "DELETE",
    `/projects/${projectId}/graph/facts?source=${encodeURIComponent(source)}&target=${encodeURIComponent(target)}`,
  );
