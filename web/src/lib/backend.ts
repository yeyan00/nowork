import type { ChannelPlatform, ChannelSummary, ChatAttachment, ChatMessage, MemberActivitiesByRun, ScheduleRun, ScheduleSummary, SendMessageResult, SessionSummary, ToolCall, WorkerSummary } from '../types';

// Lazy-loaded Tauri invoke — only available when running inside Tauri desktop shell
let _invoke: ((cmd: string, args?: Record<string, unknown>) => Promise<unknown>) | null | undefined;

async function getTauriInvoke(): Promise<typeof _invoke> {
  if (_invoke !== undefined) return _invoke;
  try {
    const tauriApi = await import('@tauri-apps/api/core');
    _invoke = tauriApi.invoke;
  } catch {
    _invoke = null;
  }
  return _invoke;
}

export interface AgentEvent {
  event: string;
  content?: string;
  reasoning?: string;
  reasoning_content?: string;
  toolCalls?: ToolCall[];
  metrics?: { input_tokens: number; output_tokens: number; total_tokens: number; duration: number };
  session_id?: string;
  run_id?: string;
  [key: string]: unknown;
}

export interface RuntimeState {
  host: string;
  port: number;
  baseUrl: string;
}

export interface HealthPayload {
  status: string;
  service: string;
  version: string;
  port?: number;
}

let runtimeStatePromise: Promise<RuntimeState | null> | null = null;

export function resetRuntimeStateCache() {
  runtimeStatePromise = null;
}

export async function readRuntimeState(): Promise<RuntimeState | null> {
  // If cached and succeeded, return it. If cached as null, retry.
  if (runtimeStatePromise) {
    const cached = await runtimeStatePromise;
    if (cached) {
      return cached;
    }
    // Cached as null — clear and retry
    runtimeStatePromise = null;
  }

  runtimeStatePromise = (async () => {
    try {
      // 1. Try Tauri command (release mode: reads from bundled resources)
      const invoke = await getTauriInvoke();
      if (invoke) {
        const jsonStr = await invoke('get_runtime_config', {}) as string;
        if (jsonStr) {
          return JSON.parse(jsonStr) as RuntimeState;
        }
      }
    } catch {
      // Tauri command not available or failed — fall through to fetch
    }

    try {
      // 2. Fallback: fetch from Vite dev server (dev mode)
      const response = await fetch('/runtime/app-runtime.json', { cache: 'no-store' });
      if (!response.ok) {
        return null;
      }

      return (await response.json()) as RuntimeState;
    } catch {
      return null;
    }
  })();

  return runtimeStatePromise;
}

/// Read backend error logs via Tauri command (release mode only).
/// Returns raw log text for display to the user.
export async function getBackendError(): Promise<string | null> {
  try {
    const invoke = await getTauriInvoke();
    if (invoke) {
      return await invoke('get_backend_error', {}) as string;
    }
  } catch {
    // Not running in Tauri or command failed
  }
  return null;
}

export async function fetchHealth(baseUrl: string): Promise<HealthPayload> {
  const response = await fetch(`${baseUrl}/health`);

  if (!response.ok) {
    throw new Error('Health request failed');
  }

  return (await response.json()) as HealthPayload;
}

export async function fetchFromApi(path: string, init?: RequestInit): Promise<Response> {
  const runtime = await readRuntimeState();
  if (!runtime) {
    throw new Error('Runtime metadata unavailable');
  }

  return fetch(`${runtime.baseUrl}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
    ...init,
  });
}

export async function listWorkers(type?: string): Promise<WorkerSummary[]> {
  const suffix = type ? `?type=${encodeURIComponent(type)}` : '';
  const response = await fetchFromApi(`/api/workers${suffix}`);

  if (!response.ok) {
    throw new Error('Failed to load workers');
  }

  return (await response.json()) as WorkerSummary[];
}

export async function createWorker(params: {
  type: string;
  name: string;
  cloneFrom?: string;
}): Promise<WorkerSummary> {
  const response = await fetchFromApi('/api/workers', {
    method: 'POST',
    body: JSON.stringify({
      type: params.type,
      name: params.name,
      description: '',
      status: 'active',
      clone_from: params.cloneFrom || null,
    }),
  });

  if (response.status === 409) {
    const detail = await response.json().catch(() => ({}));
    throw new Error((detail as { detail?: string }).detail || 'Name already exists');
  }
  if (!response.ok) {
    throw new Error('Failed to create worker');
  }

  return (await response.json()) as WorkerSummary;
}

export async function updateWorker(workerId: string, payload: Partial<WorkerSummary>): Promise<WorkerSummary> {
  const response = await fetchFromApi(`/api/workers/${workerId}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    throw new Error('Failed to save worker');
  }

  return (await response.json()) as WorkerSummary;
}

export async function listSessions(workerId: string): Promise<SessionSummary[]> {
  const response = await fetchFromApi(`/api/workers/${workerId}/sessions`);

  if (!response.ok) {
    throw new Error('Failed to load sessions');
  }

  return (await response.json()) as SessionSummary[];
}

export async function createSession(workerId: string, title: string, workspaces?: string[] | null): Promise<SessionSummary> {
  const response = await fetchFromApi(`/api/workers/${workerId}/sessions`, {
    method: 'POST',
    body: JSON.stringify({ title, workspaces: workspaces ?? null }),
  });

  if (!response.ok) {
    throw new Error('Failed to create session');
  }

  return (await response.json()) as SessionSummary;
}

export async function updateSession(sessionId: string, payload: { title?: string; workspaces?: string[] | null; modelOverride?: string | null; learningEnabled?: boolean | null }): Promise<SessionSummary> {
  const response = await fetchFromApi(`/api/sessions/${sessionId}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    throw new Error('Failed to update session');
  }

  return (await response.json()) as SessionSummary;
}

export async function cloneSession(sessionId: string, cloneFromRun?: number): Promise<SessionSummary> {
  const url = cloneFromRun !== undefined
    ? `/api/sessions/${sessionId}/clone?clone_from_run=${cloneFromRun}`
    : `/api/sessions/${sessionId}/clone`;
  const response = await fetchFromApi(url, { method: 'POST' });

  if (!response.ok) {
    throw new Error('Failed to clone session');
  }

  return (await response.json()) as SessionSummary;
}

export async function compactSession(sessionId: string): Promise<{ ok: boolean; segment_id: string }> {
  const response = await fetchFromApi(`/api/compaction-sessions/${sessionId}/compact`, { method: 'POST' });

  if (!response.ok) {
    throw new Error('Failed to compact session');
  }

  return (await response.json()) as { ok: boolean; segment_id: string };
}

export interface MessagesPage {
  messages: ChatMessage[];
  total: number;
  has_more: boolean;
  compactedSegments?: number;
  memberActivitiesByRun?: MemberActivitiesByRun[];
}

export async function listMessages(sessionId: string, limit = 20, offset = 0): Promise<MessagesPage> {
  const response = await fetchFromApi(`/api/sessions/${sessionId}/messages?limit=${limit}&offset=${offset}`);

  if (!response.ok) {
    throw new Error('Failed to load messages');
  }

  return (await response.json()) as MessagesPage;
}

export async function sendMessage(sessionId: string, content: string, attachments?: ChatAttachment[]): Promise<SendMessageResult> {
  const response = await fetchFromApi(`/api/sessions/${sessionId}/messages`, {
    method: 'POST',
    body: JSON.stringify({ content, attachments: attachments ?? [] }),
  });

  if (!response.ok) {
    throw new Error('Failed to send message');
  }

  return (await response.json()) as SendMessageResult;
}

export async function sendMessageStream(
  sessionId: string,
  content: string,
  attachments: ChatAttachment[],
  onEvent: (event: AgentEvent) => void,
): Promise<void> {
  const runtime = await readRuntimeState();
  if (!runtime) {
    throw new Error('Runtime metadata unavailable');
  }

  const response = await fetch(`${runtime.baseUrl}/api/sessions/${sessionId}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content, attachments }),
  });

  if (!response.ok) {
    throw new Error('Failed to send message');
  }

  const contentType = response.headers.get('content-type') || '';

  if (contentType.includes('text/event-stream')) {
    const reader = response.body?.getReader();
    if (!reader) throw new Error('No response body');

    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith(':')) continue;

        if (trimmed.startsWith('data:')) {
          const dataStr = trimmed.slice(5).trim();
          if (dataStr) {
            try {
              onEvent(JSON.parse(dataStr) as AgentEvent);
            } catch {
            }
          }
        }
      }
    }
  } else {
    const result = (await response.json()) as SendMessageResult;
    onEvent({
      event: 'RunCompleted',
      content: result.workerMessage.content,
      toolCalls: result.workerMessage.toolCalls,
      reasoning: result.workerMessage.reasoning,
      metrics: {
        input_tokens: result.tokenUsage.input,
        output_tokens: result.tokenUsage.output,
        total_tokens: result.tokenUsage.total,
        duration: 0,
      },
    });
  }
}

export async function cancelRun(runId: string): Promise<{ ok: boolean; run_id: string }> {
  const response = await fetchFromApi(`/api/runs/${runId}/cancel`, { method: 'POST' });
  if (!response.ok) throw new Error('Failed to cancel run');
  return (await response.json()) as { ok: boolean; run_id: string };
}

export interface ContinueRunParams {
  runId: string;
  sessionId: string;
  workerId: string;
  confirmed: boolean;
  alwaysAllowDir?: string;
  updatedTools: Array<{
    toolCallId: string;
    toolName: string;
    toolArgs: Record<string, unknown>;
    requiresConfirmation: boolean;
  }>;
}

export async function continueRunStream(
  params: ContinueRunParams,
  onEvent: (event: AgentEvent) => void,
): Promise<void> {
  const runtime = await readRuntimeState();
  if (!runtime) throw new Error('Runtime metadata unavailable');

  const body = {
    confirmed: params.confirmed,
    session_id: params.sessionId,
    worker_id: params.workerId,
    always_allow_dir: params.alwaysAllowDir || null,
    updated_tools: params.updatedTools,
  };

  const response = await fetch(`${runtime.baseUrl}/api/runs/${params.runId}/continue/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    // Fallback: try non-streaming endpoint
    const fallbackResponse = await fetchFromApi(`/api/runs/${params.runId}/continue`, {
      method: 'POST',
      body: JSON.stringify(body),
    });
    if (!fallbackResponse.ok) throw new Error('Failed to continue run');
    const result = await fallbackResponse.json() as { ok: boolean; run_id: string; status: string };
    onEvent({ event: 'RunCompleted', content: 'Run continued' });
    return;
  }

  const reader = response.body?.getReader();
  if (!reader) throw new Error('No response body');

  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith(':')) continue;

      if (trimmed.startsWith('data:')) {
        const dataStr = trimmed.slice(5).trim();
        if (dataStr) {
          try {
            onEvent(JSON.parse(dataStr) as AgentEvent);
          } catch {
          }
        }
      }
    }
  }
}

export type SchedulePayload = Omit<ScheduleSummary, 'id' | 'workerName' | 'lastRunAt' | 'nextRunAt' | 'lastStatus' | 'lastError' | 'createdAt' | 'updatedAt'>;

export async function listSchedules(): Promise<ScheduleSummary[]> {
  const response = await fetchFromApi('/api/schedules');
  if (!response.ok) throw new Error('Failed to load schedules');
  return (await response.json()) as ScheduleSummary[];
}

export async function createSchedule(payload: SchedulePayload): Promise<ScheduleSummary> {
  const response = await fetchFromApi('/api/schedules', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error('Failed to create schedule');
  return (await response.json()) as ScheduleSummary;
}

export async function updateSchedule(id: string, payload: SchedulePayload): Promise<ScheduleSummary> {
  const response = await fetchFromApi(`/api/schedules/${id}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error('Failed to update schedule');
  return (await response.json()) as ScheduleSummary;
}

export async function deleteSchedule(id: string): Promise<{ ok: boolean; id: string }> {
  const response = await fetchFromApi(`/api/schedules/${id}`, { method: 'DELETE' });
  if (!response.ok) throw new Error('Failed to delete schedule');
  return (await response.json()) as { ok: boolean; id: string };
}

export async function runSchedule(id: string): Promise<{ ok: boolean; run: ScheduleSummary; sessionId: string }> {
  const response = await fetchFromApi(`/api/schedules/${id}/run`, { method: 'POST' });
  if (!response.ok) throw new Error('Failed to run schedule');
  return (await response.json()) as { ok: boolean; run: ScheduleSummary; sessionId: string };
}

export async function listScheduleRuns(id: string, limit = 20): Promise<ScheduleRun[]> {
  const response = await fetchFromApi(`/api/schedules/${id}/runs?limit=${limit}`);
  if (!response.ok) throw new Error('Failed to load schedule runs');
  return (await response.json()) as ScheduleRun[];
}

export interface SkillSummary {
  name: string;
  description: string;
  sourcePath: string;
  scripts: string[];
  references: string[];
  instructions: string;
}

export async function listSkills(): Promise<SkillSummary[]> {
  const response = await fetchFromApi('/api/skills');
  if (!response.ok) throw new Error('Failed to load skills');
  return (await response.json()) as SkillSummary[];
}

export async function getSkillFile(skillName: string, filePath: string): Promise<string> {
  const response = await fetchFromApi(`/api/skills/${skillName}/files/${filePath}`);
  if (!response.ok) throw new Error('Failed to load skill file');
  const data = (await response.json()) as { content: string };
  return data.content;
}

export interface SkillFileNode {
  name: string;
  size: number;
}

export async function listSkillFiles(skillName: string): Promise<SkillFileNode[]> {
  const response = await fetchFromApi(`/api/skills/${skillName}/tree`);
  if (!response.ok) throw new Error('Failed to load skill files');
  return (await response.json()) as SkillFileNode[];
}

export async function installSkill(source: string, overwrite = false): Promise<{ ok: boolean; name?: string; duplicate?: boolean; error?: string }> {
  const response = await fetchFromApi('/api/skills/install', {
    method: 'POST',
    body: JSON.stringify({ source, overwrite }),
  });
  return (await response.json()) as { ok: boolean; name?: string; duplicate?: boolean; error?: string };
}

export async function deleteSkill(skillName: string): Promise<{ ok: boolean; name?: string; error?: string }> {
  const response = await fetchFromApi(`/api/skills/${skillName}`, { method: 'DELETE' });
  if (!response.ok) throw new Error('Failed to delete skill');
  return (await response.json()) as { ok: boolean; name?: string; error?: string };
}

export interface ModelInfo {
  id: string;
  localId: string;
  name: string;
  image: boolean;
  video: boolean;
  contextWindow?: number;
}

export interface ProviderInfo {
  id: string;
  name: string;
  type: string;
  provider: string;
  baseUrl: string;
  apiKey: string;
  models: ModelInfo[];
}

export async function listModels(): Promise<{ providers: ProviderInfo[]; default_model: string }> {
  const response = await fetchFromApi('/api/models');
  if (!response.ok) throw new Error('Failed to load models');
  return (await response.json()) as { providers: ProviderInfo[]; default_model: string };
}

export async function createProvider(payload: {
  id: string;
  name: string;
  type?: string;
  provider?: string;
  baseUrl: string;
  apiKey: string;
}): Promise<ProviderInfo> {
  const response = await fetchFromApi('/api/providers', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error('Failed to create provider');
  return (await response.json()) as ProviderInfo;
}

export async function updateProvider(
  providerId: string,
  payload: Partial<ProviderInfo>,
): Promise<ProviderInfo> {
  const response = await fetchFromApi(`/api/providers/${providerId}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error('Failed to update provider');
  return (await response.json()) as ProviderInfo;
}

export async function deleteProvider(
  providerId: string,
): Promise<{ ok: boolean; id: string }> {
  const response = await fetchFromApi(`/api/providers/${providerId}`, {
    method: 'DELETE',
  });
  if (!response.ok) throw new Error('Failed to delete provider');
  return (await response.json()) as { ok: boolean; id: string };
}

export async function fetchRemoteModels(
  baseUrl: string,
  apiKey?: string,
): Promise<{ id: string; name: string }[]> {
  const response = await fetchFromApi('/api/providers/fetch-models', {
    method: 'POST',
    body: JSON.stringify({ baseUrl, apiKey }),
  });
  if (!response.ok) throw new Error('Failed to fetch models');
  const data = (await response.json()) as { models: { id: string; name: string }[] };
  return data.models;
}

export async function setDefaultModel(modelRef: string): Promise<{ ok: boolean; default_model: string }> {
  const response = await fetchFromApi('/api/default-model', {
    method: 'PUT',
    body: JSON.stringify({ model: modelRef }),
  });
  if (!response.ok) throw new Error('Failed to set default model');
  return (await response.json()) as { ok: boolean; default_model: string };
}

export interface LogData {
  lines: string[];
  total: number;
  offset: number;
  has_more: boolean;
  files: string[];
}

export async function fetchLogs(lines = 200, offset = 0, file?: string): Promise<LogData> {
  const params = new URLSearchParams();
  params.set('lines', String(lines));
  params.set('offset', String(offset));
  if (file) params.set('file', file);
  const response = await fetchFromApi(`/api/logs?${params.toString()}`);
  if (!response.ok) throw new Error('Failed to fetch logs');
  return (await response.json()) as LogData;
}

export interface ToolSubDef {
  id: string;
  name: string;
  default: boolean;
  required?: boolean;
}

export interface ToolCatalogEntry {
  id: string;
  name: string;
  module: string;
  description: string;
  tools: ToolSubDef[];
}

export async function listToolsCatalog(): Promise<ToolCatalogEntry[]> {
  const response = await fetchFromApi('/api/tools-catalog');
  if (!response.ok) throw new Error('Failed to load tools catalog');
  return (await response.json()) as ToolCatalogEntry[];
}

export interface MCPToolConfig {
  name: string;
  description: string;
  enabled: boolean;
}

export interface MCPServer {
  name: string;
  transport: 'stdio' | 'sse' | 'streamable-http';
  command?: string;
  url?: string;
  env?: Record<string, string>;
  timeout_seconds?: number;
  tools?: MCPToolConfig[];
  exclude_tools?: string[];
  include_tools?: string[];
  verified?: boolean;
}

export async function listMCPServers(): Promise<MCPServer[]> {
  const response = await fetchFromApi('/api/mcp');
  if (!response.ok) throw new Error('Failed to load MCP servers');
  return (await response.json()) as MCPServer[];
}

export async function saveMCPServers(servers: MCPServer[]): Promise<MCPServer[]> {
  const response = await fetchFromApi('/api/mcp', {
    method: 'PUT',
    body: JSON.stringify({ servers }),
  });
  if (!response.ok) throw new Error('Failed to save MCP servers');
  return (await response.json()) as MCPServer[];
}

export interface MCPTestResult {
  ok: boolean;
  tools?: { name: string; description: string }[];
  error?: string;
}

export async function testMCPConnection(payload: {
  transport: string;
  command?: string;
  url?: string;
  env?: Record<string, string>;
  timeout_seconds?: number;
}): Promise<MCPTestResult> {
  const response = await fetchFromApi('/api/mcp/test', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error('Failed to test MCP connection');
  return (await response.json()) as MCPTestResult;
}

// =============================================================================
// Learning Content APIs
// =============================================================================

export interface LearningMemoryEntry {
  memory_id: string;
  memory: string;
  topics?: string[];
  user_id?: string;
  input?: string;
  created_at?: string;
  updated_at?: string;
  feedback?: string;
}

export interface LearningMemoriesResponse {
  worker_id: string;
  user_id: string;
  memories: LearningMemoryEntry[];
  total: number;
}

export interface SessionContextResponse {
  worker_id: string;
  session_id: string;
  context: Record<string, unknown> | null;
  summary: string | null;
  messages_count?: number;
}

export interface EntityMemoryResponse {
  worker_id: string;
  entities: Array<{
    id: string;
    name: string;
    content: string;
    meta_data?: Record<string, unknown>;
  }>;
  total: number;
}

export interface DecisionLogResponse {
  worker_id: string;
  session_id?: string;
  decisions: Array<Record<string, unknown>>;
  total?: number;
}

export async function getUserProfile(workerId: string, userId: string): Promise<LearningMemoriesResponse> {
  const response = await fetchFromApi(`/api/workers/${encodeURIComponent(workerId)}/learning/user-profile?user_id=${encodeURIComponent(userId)}`);
  if (!response.ok) throw new Error('Failed to get user profile');
  return (await response.json()) as LearningMemoriesResponse;
}

export async function getUserMemory(workerId: string, userId: string): Promise<LearningMemoriesResponse> {
  const response = await fetchFromApi(`/api/workers/${workerId}/learning/user-memory?user_id=${encodeURIComponent(userId)}`);
  if (!response.ok) throw new Error('Failed to get user memory');
  return (await response.json()) as LearningMemoriesResponse;
}

export async function addUserMemory(workerId: string, userId: string, memory: string): Promise<{ ok: boolean; memory_id: string }> {
  const response = await fetchFromApi(`/api/workers/${workerId}/learning/user-memory?user_id=${encodeURIComponent(userId)}`, {
    method: 'POST',
    body: JSON.stringify({ memory }),
  });
  if (!response.ok) throw new Error('Failed to add user memory');
  return (await response.json()) as { ok: boolean; memory_id: string };
}

export async function updateUserMemory(workerId: string, memoryId: string, memory: string): Promise<{ ok: boolean; memory_id: string }> {
  const response = await fetchFromApi(`/api/workers/${workerId}/learning/user-memory/${encodeURIComponent(memoryId)}`, {
    method: 'PUT',
    body: JSON.stringify({ memory }),
  });
  if (!response.ok) throw new Error('Failed to update user memory');
  return (await response.json()) as { ok: boolean; memory_id: string };
}

export async function deleteUserMemory(workerId: string, memoryId: string, userId?: string): Promise<{ ok: boolean; memory_id: string }> {
  const params = userId ? `?user_id=${encodeURIComponent(userId)}` : '';
  const response = await fetchFromApi(`/api/workers/${workerId}/learning/user-memory/${encodeURIComponent(memoryId)}${params}`, {
    method: 'DELETE',
  });
  if (!response.ok) throw new Error('Failed to delete user memory');
  return (await response.json()) as { ok: boolean; memory_id: string };
}

export async function getSessionContext(workerId: string, sessionId: string): Promise<SessionContextResponse> {
  const response = await fetchFromApi(`/api/workers/${workerId}/learning/session-context?session_id=${encodeURIComponent(sessionId)}`);
  if (!response.ok) throw new Error('Failed to get session context');
  return (await response.json()) as SessionContextResponse;
}

export async function getEntityMemory(workerId: string, entityId?: string, entityType?: string): Promise<EntityMemoryResponse> {
  const params = new URLSearchParams();
  if (entityId) params.set('entity_id', entityId);
  if (entityType) params.set('entity_type', entityType);
  const qs = params.toString() ? `?${params.toString()}` : '';
  const response = await fetchFromApi(`/api/workers/${workerId}/learning/entity-memory${qs}`);
  if (!response.ok) throw new Error('Failed to get entity memory');
  return (await response.json()) as EntityMemoryResponse;
}

export async function getDecisionLog(workerId: string, sessionId?: string): Promise<DecisionLogResponse> {
  const params = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : '';
  const response = await fetchFromApi(`/api/workers/${workerId}/learning/decision-log${params}`);
  if (!response.ok) throw new Error('Failed to get decision log');
  return (await response.json()) as DecisionLogResponse;
}


export interface KnowledgeBase {
  id: string;
  name: string;
  description: string;
  paths: string[];
  embedder: Record<string, unknown>;
  vector_db: Record<string, unknown>;
  wiki_mode?: boolean;
  purpose?: string;
  auto_sync?: boolean;
  language?: string;
  _ref: string;
}

// ── Wiki API Types ──────────────────────────────────────────────

export interface WikiPage {
  path: string;
  meta: Record<string, unknown>;
  body: string;
  raw: string;
  title: string;
}

export interface WikiPageSummary {
  path: string;
  title: string;
  type: string;
  category: string;
}

export interface WikiSearchResult {
  path: string;
  title: string;
  title_match: boolean;
  score: number;
  snippet: string;
}

export interface WikiStats {
  total: number;
  by_type: Record<string, number>;
  by_category: Record<string, number>;
}

export interface WikiLintResult {
  broken_links: Array<{ source: string; target: string }>;
  orphan_pages: string[];
  empty_pages: string[];
  missing_sources: string[];
  total_pages: number;
  total_links: number;
  healthy: boolean;
  warnings: number;
}

export interface WikiSyncResult {
  ok: boolean;
  id: string;
  pages_written: number;
  pages: string[];
  cancelled?: boolean;
}

export interface WikiIngestResult {
  ok: boolean;
  id: string;
  pages_written: number;
  pages: string[];
}

export async function listKnowledgeBases(): Promise<KnowledgeBase[]> {
  const response = await fetchFromApi('/api/knowledge');
  if (!response.ok) throw new Error('Failed to list knowledge bases');
  return (await response.json()) as KnowledgeBase[];
}

export async function getKnowledgeBase(id: string): Promise<KnowledgeBase> {
  const response = await fetchFromApi(`/api/knowledge/${encodeURIComponent(id)}`);
  if (!response.ok) throw new Error('Failed to get knowledge base');
  return (await response.json()) as KnowledgeBase;
}

export async function createKnowledgeBase(payload: Partial<KnowledgeBase>): Promise<KnowledgeBase> {
  const response = await fetchFromApi('/api/knowledge', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error('Failed to create knowledge base');
  return (await response.json()) as KnowledgeBase;
}

export async function updateKnowledgeBase(id: string, payload: { name?: string; description?: string; wiki_mode?: boolean; purpose?: string; auto_sync?: boolean; language?: string; config?: { paths?: string[]; embedder?: Record<string, unknown>; vector_db?: Record<string, unknown> } }): Promise<KnowledgeBase> {
  const response = await fetchFromApi(`/api/knowledge/${encodeURIComponent(id)}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error('Failed to update knowledge base');
  return (await response.json()) as KnowledgeBase;
}

export async function deleteKnowledgeBase(id: string): Promise<{ ok: boolean }> {
  const response = await fetchFromApi(`/api/knowledge/${encodeURIComponent(id)}`, { method: 'DELETE' });
  if (!response.ok) throw new Error('Failed to delete knowledge base');
  return (await response.json()) as { ok: boolean };
}

export async function reloadKnowledgeBase(id: string): Promise<{ ok: boolean }> {
  const response = await fetchFromApi(`/api/knowledge/${encodeURIComponent(id)}/reload`, { method: 'POST' });
  if (!response.ok) throw new Error('Failed to reload knowledge base');
  return (await response.json()) as { ok: boolean };
}


// =============================================================================
// Wiki Knowledge APIs
// =============================================================================

export async function syncWikiKnowledgeBase(id: string, signal?: AbortSignal): Promise<WikiSyncResult> {
  const response = await fetchFromApi(`/api/knowledge/${encodeURIComponent(id)}/sync`, { method: 'POST', signal });
  if (!response.ok) throw new Error('Failed to sync wiki knowledge base');
  return (await response.json()) as WikiSyncResult;
}

export async function cancelWikiSync(id: string): Promise<{ ok: boolean }> {
  const response = await fetchFromApi(`/api/knowledge/${encodeURIComponent(id)}/sync/cancel`, { method: 'POST' });
  if (!response.ok) throw new Error('Failed to cancel sync');
  return (await response.json()) as { ok: boolean };
}

export async function ingestWikiFiles(id: string, files: string[], force = false): Promise<WikiIngestResult> {
  const response = await fetchFromApi(`/api/knowledge/${encodeURIComponent(id)}/ingest`, {
    method: 'POST',
    body: JSON.stringify({ files, force }),
  });
  if (!response.ok) throw new Error('Failed to ingest files');
  return (await response.json()) as WikiIngestResult;
}

export async function listWikiPages(id: string, type?: string, search?: string): Promise<WikiPageSummary[]> {
  const params = new URLSearchParams();
  if (type) params.set('type', type);
  if (search) params.set('search', search);
  const qs = params.toString() ? `?${params.toString()}` : '';
  const response = await fetchFromApi(`/api/knowledge/${encodeURIComponent(id)}/wiki/pages${qs}`);
  if (!response.ok) throw new Error('Failed to list wiki pages');
  return (await response.json()) as WikiPageSummary[];
}

export async function readWikiPage(id: string, pagePath: string): Promise<WikiPage> {
  const response = await fetchFromApi(`/api/knowledge/${encodeURIComponent(id)}/wiki/page/${pagePath}`);
  if (!response.ok) throw new Error('Failed to read wiki page');
  return (await response.json()) as WikiPage;
}

export async function writeWikiPage(id: string, pagePath: string, content: string): Promise<{ ok: boolean; path: string }> {
  const response = await fetchFromApi(`/api/knowledge/${encodeURIComponent(id)}/wiki/page/${pagePath}`, {
    method: 'PUT',
    body: JSON.stringify({ content }),
  });
  if (!response.ok) throw new Error('Failed to write wiki page');
  return (await response.json()) as { ok: boolean; path: string };
}

export async function deleteWikiPage(id: string, pagePath: string): Promise<{ ok: boolean; path: string }> {
  const response = await fetchFromApi(`/api/knowledge/${encodeURIComponent(id)}/wiki/page/${pagePath}`, {
    method: 'DELETE',
  });
  if (!response.ok) throw new Error('Failed to delete wiki page');
  return (await response.json()) as { ok: boolean; path: string };
}

export async function searchWikiPages(id: string, query: string, maxResults = 20): Promise<WikiSearchResult[]> {
  const response = await fetchFromApi(`/api/knowledge/${encodeURIComponent(id)}/wiki/search`, {
    method: 'POST',
    body: JSON.stringify({ query, max_results: maxResults }),
  });
  if (!response.ok) throw new Error('Failed to search wiki pages');
  return (await response.json()) as WikiSearchResult[];
}

export async function getWikiStats(id: string): Promise<WikiStats> {
  const response = await fetchFromApi(`/api/knowledge/${encodeURIComponent(id)}/wiki/stats`);
  if (!response.ok) throw new Error('Failed to get wiki stats');
  return (await response.json()) as WikiStats;
}

export async function lintWikiKnowledgeBase(id: string): Promise<WikiLintResult> {
  const response = await fetchFromApi(`/api/knowledge/${encodeURIComponent(id)}/wiki/lint`, { method: 'POST' });
  if (!response.ok) throw new Error('Failed to lint wiki knowledge base');
  return (await response.json()) as WikiLintResult;
}

export interface WikiGraphNode {
  id: string;
  title: string;
  type: string;
  path: string;
  group: string;
}

export interface WikiGraphEdge {
  source: string;
  target: string;
  source_path: string;
}

export interface WikiGraphData {
  nodes: WikiGraphNode[];
  edges: WikiGraphEdge[];
  stats: {
    total_nodes: number;
    total_edges: number;
    by_type: Record<string, number>;
    orphan_nodes: string[];
  };
}

export async function getWikiGraph(id: string): Promise<WikiGraphData> {
  const response = await fetchFromApi(`/api/knowledge/${encodeURIComponent(id)}/wiki/graph`);
  if (!response.ok) throw new Error('Failed to get wiki graph');
  return (await response.json()) as WikiGraphData;
}


export interface ExtensionInfo {
  id: string;
  name: string;
  description: string;
  category: string;
  pip_packages: string[];
  install_size: string;
  status: 'installed' | 'not_installed';
  version: string;
}

export async function listExtensions(): Promise<ExtensionInfo[]> {
  const response = await fetchFromApi('/api/extensions');
  if (!response.ok) throw new Error('Failed to list extensions');
  return (await response.json()) as ExtensionInfo[];
}

export async function installExtension(extId: string): Promise<{ ok: boolean; error: string }> {
  const response = await fetchFromApi(`/api/extensions/${encodeURIComponent(extId)}/install`, { method: 'POST' });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error((data as Record<string, string>).detail || 'Install failed');
  }
  return (await response.json()) as { ok: boolean; error: string };
}

export async function uninstallExtension(extId: string): Promise<{ ok: boolean; error: string }> {
  const response = await fetchFromApi(`/api/extensions/${encodeURIComponent(extId)}/uninstall`, { method: 'POST' });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error((data as Record<string, string>).detail || 'Uninstall failed');
  }
  return (await response.json()) as { ok: boolean; error: string };
}


// =============================================================================
// Session Compaction APIs
// =============================================================================

export interface SessionCompactionConfig {
  enabled: boolean;
  context_usage_threshold: number;
  context_reserve_tokens: number;
  summary_style: string;
  preserve_recent_messages: number;
  max_summaries_injected: number;
  summary_model: string | null;
}

export interface SessionConfigResponse {
  session: {
    db_file: string;
    compaction: SessionCompactionConfig;
  };
  compaction: SessionCompactionConfig;
}

export async function getSessionConfig(): Promise<SessionConfigResponse> {
  const response = await fetchFromApi('/api/session-config');
  if (!response.ok) throw new Error('Failed to get session config');
  return (await response.json()) as SessionConfigResponse;
}

export async function updateSessionConfig(updates: {
  enabled?: boolean;
  context_usage_threshold?: number;
  context_reserve_tokens?: number;
  preserve_recent_messages?: number;
  max_summaries_injected?: number;
}): Promise<{ session: unknown }> {
  const response = await fetchFromApi('/api/session-config', {
    method: 'PUT',
    body: JSON.stringify(updates),
  });
  if (!response.ok) throw new Error('Failed to update session config');
  return (await response.json()) as { session: unknown };
}

// =============================================================================
// Agent Types & Prerequisites
// =============================================================================

export interface AgentTypeInfo {
  id: string;
  name: string;
  description: string;
  framework: string;
  prerequisites: string[];
  supports: string[];
  config_fields: AgentTypeConfigField[];
}

export interface AgentTypeConfigField {
  key: string;
  type: 'string' | 'textarea' | 'select' | 'multiselect' | 'number';
  label: string;
  placeholder?: string;
  options?: string[];
  default?: unknown;
  optional?: boolean;
}

export interface PrerequisiteStep {
  id: string;
  name: string;
  installed: boolean;
  version: string | null;
  blocked?: boolean;
  install_cmd?: string;
  install_label?: string;
}

export interface PrerequisiteStatus {
  ready: boolean;
  chain: PrerequisiteStep[];
  missing: string[];
  install_cmd: string | null;
  install_label: string | null;
}

export async function listAgentTypes(): Promise<AgentTypeInfo[]> {
  const response = await fetchFromApi('/api/agent-types');
  if (!response.ok) throw new Error('Failed to list agent types');
  return (await response.json()) as AgentTypeInfo[];
}

export async function checkPrerequisites(agentType: string): Promise<PrerequisiteStatus> {
  const response = await fetchFromApi(`/api/prerequisites/${encodeURIComponent(agentType)}`);
  if (!response.ok) throw new Error('Failed to check prerequisites');
  return (await response.json()) as PrerequisiteStatus;
}

export async function installPrerequisite(command: string): Promise<Response> {
  return fetchFromApi('/api/prerequisites/install', {
    method: 'POST',
    body: JSON.stringify({ command }),
  });
}

// =============================================================================
// Translation
// =============================================================================

export async function translateText(text: string, targetLang: string = 'zh-CN'): Promise<string> {
  const response = await fetchFromApi('/api/translate', {
    method: 'POST',
    body: JSON.stringify({ text, target_lang: targetLang }),
  });
  if (!response.ok) throw new Error('Translation failed');
  const data = await response.json() as { translated: string };
  return data.translated;
}

// ── Channel APIs ────────────────────────────────────────────

export async function listChannels(): Promise<ChannelSummary[]> {
  const response = await fetchFromApi('/api/channels');
  if (!response.ok) throw new Error('Failed to load channels');
  return (await response.json()) as ChannelSummary[];
}

export async function listChannelPlatforms(): Promise<ChannelPlatform[]> {
  const response = await fetchFromApi('/api/channels/platforms');
  if (!response.ok) throw new Error('Failed to load platforms');
  return (await response.json()) as ChannelPlatform[];
}

export async function getChannel(channelId: string): Promise<ChannelSummary> {
  const response = await fetchFromApi(`/api/channels/${encodeURIComponent(channelId)}`);
  if (!response.ok) throw new Error('Failed to load channel');
  return (await response.json()) as ChannelSummary;
}

export async function createChannel(params: {
  id: string; platform: string; name: string; enabled: boolean;
  worker_id: string; config: Record<string, unknown>;
}): Promise<ChannelSummary> {
  const response = await fetchFromApi('/api/channels', {
    method: 'POST',
    body: JSON.stringify(params),
  });
  if (!response.ok) {
    if (response.status === 409) {
      const detail = await response.json().catch(() => ({}));
      throw new Error((detail as { detail?: string }).detail || 'Channel already exists');
    }
    const detail = await response.json().catch(() => ({}));
    throw new Error((detail as { detail?: string }).detail || 'Failed to create channel');
  }
  return (await response.json()) as ChannelSummary;
}

export async function updateChannel(channelId: string, params: {
  name?: string; enabled?: boolean; worker_id?: string; config?: Record<string, unknown>;
}): Promise<ChannelSummary> {
  const response = await fetchFromApi(`/api/channels/${encodeURIComponent(channelId)}`, {
    method: 'PUT',
    body: JSON.stringify(params),
  });
  if (!response.ok) {
    if (response.status === 409) {
      const detail = await response.json().catch(() => ({}));
      throw new Error((detail as { detail?: string }).detail || 'Duplicate channel');
    }
    const detail = await response.json().catch(() => ({}));
    throw new Error((detail as { detail?: string }).detail || 'Failed to update channel');
  }
  return (await response.json()) as ChannelSummary;
}

export async function deleteChannel(channelId: string): Promise<void> {
  const response = await fetchFromApi(`/api/channels/${encodeURIComponent(channelId)}`, {
    method: 'DELETE',
  });
  if (!response.ok) throw new Error('Failed to delete channel');
}

export async function testChannel(channelId: string): Promise<{ ok: boolean; error?: string; status?: string; detail?: string }> {
  const response = await fetchFromApi(`/api/channels/${encodeURIComponent(channelId)}/test`, {
    method: 'POST',
  });
  if (!response.ok) throw new Error('Failed to test channel');
  return (await response.json()) as { ok: boolean; error?: string; status?: string; detail?: string };
}
