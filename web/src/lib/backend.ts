import type { ChatAttachment, ChatMessage, MemberActivitiesByRun, ScheduleRun, ScheduleSummary, SendMessageResult, SessionSummary, ToolCall, WorkerSummary } from '../types';

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

export async function fetchHealth(baseUrl: string): Promise<HealthPayload> {
  const response = await fetch(`${baseUrl}/health`);

  if (!response.ok) {
    throw new Error('Health request failed');
  }

  return (await response.json()) as HealthPayload;
}

async function fetchFromApi(path: string, init?: RequestInit): Promise<Response> {
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

export async function updateSession(sessionId: string, payload: { title?: string; workspaces?: string[] | null }): Promise<SessionSummary> {
  const response = await fetchFromApi(`/api/sessions/${sessionId}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    throw new Error('Failed to update session');
  }

  return (await response.json()) as SessionSummary;
}

export interface MessagesPage {
  messages: ChatMessage[];
  total: number;
  has_more: boolean;
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
  _ref: string;
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

export async function updateKnowledgeBase(id: string, payload: { name?: string; description?: string; config?: { paths?: string[]; embedder?: Record<string, unknown>; vector_db?: Record<string, unknown> } }): Promise<KnowledgeBase> {
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
