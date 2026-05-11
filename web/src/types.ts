export type WorkerType = 'Agent' | 'Team' | 'Workflow';

export type AppPage =
  | 'Chat'
  | 'Workers'
  | 'Channels'
  | 'Schedules'
  | 'Skills'
  | 'Extensions'
  | 'MCP'
  | 'Knowledge'
  | 'Models'
  | 'Settings';

export interface WorkerSummary {
  id: string;
  name: string;
  type: WorkerType;
  agentType?: string;
  i18n?: Record<string, { description?: string }>;
  description: string;
  status: string;
  recent: string;
  config?: Record<string, unknown>;
}

export interface ToolCall {
  toolCallId: string;
  toolName: string;
  toolArgs: Record<string, unknown>;
  result: unknown;
  error: string | null;
}

export interface MemberActivity {
  agentName: string;
  agentId: string;
  status: 'running' | 'completed' | 'error';
  toolCalls: ToolCall[];
  content: string;
}

export interface MemberActivitiesByRun {
  runId: string;
  activities: MemberActivity[];
}

export interface ChatAttachment {
  id: string;
  kind: 'file' | 'image' | 'video';
  path: string;
  name: string;
  mimeType?: string;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'worker' | 'system';
  content: string;
  meta?: string;
  contextSize?: number;     // last ModelRequestCompleted.input_tokens (context window size)
  outputTokens?: number;    // last ModelRequestCompleted.output_tokens
  toolCalls?: ToolCall[];
  reasoning?: string;
  streaming?: boolean;
  senderName?: string;
  runIndex?: number;        // which run this message belongs to (for clone-from-message)
}

export interface SessionSummary {
  id: string;
  workerId: string;
  title: string;
  workspaces?: string[] | null;
  modelOverride?: string | null;
  learningEnabled?: boolean | null;
  createdAt: string;
  updatedAt?: string;
  hasRunningRun?: boolean;
  totalInputTokens?: number;   // cumulative input tokens from DB
  totalOutputTokens?: number;  // cumulative output tokens from DB
}

export interface TokenUsage {
  input: number;
  output: number;
  total: number;
  duration: number;
}

export interface SendMessageResult {
  userMessage: ChatMessage;
  workerMessage: ChatMessage;
  tokenUsage: TokenUsage;
}

export interface ManagementCard {
  title: string;
  description: string;
  meta: string;
}

export interface WorkspaceBinding {
  path: string;
  permission: 'read' | 'read-write';
}

// ── File Preview Types ──────────────────────────────────────────

export interface FileNode {
  name: string;
  path: string;
  isDirectory: boolean;
  isFile: boolean;
  size: number;
  mtimeMs: number;
  extension?: string;
}

export type FileCategory = 'image' | 'markdown' | 'json' | 'html' | 'style' | 'pdf' | 'code';

export interface PreviewingFile {
  workspacePath: string;
  path: string;
  name: string;
  extension?: string;
  content: string;
  category: FileCategory;
  source: 'tree' | 'message';
  toolCallId?: string;
  messageId?: string;
}

export interface WorkspaceInfo {
  path: string;
  name: string;
  permission: 'read' | 'read-write';
}

// ── Tool Approval Types ──────────────────────────────────────────

export interface ToolApprovalRequest {
  runId: string;
  approvals: ToolApprovalItem[];
}

export interface ToolApprovalItem {
  toolCallId: string;
  toolName: string;
  description: string;
  toolArgs: Record<string, unknown>;
}

export interface ModelConfig {
  provider: string;
  model: string;
  temperature?: number;
}

export interface TeamMember {
  agentId: string;
  agentName: string;
  inheritTeamWorkspace: boolean;
  role?: string;
}

export interface AgentDetail {
  id: string;
  name: string;
  description: string;
  workspaces: WorkspaceBinding[];
  knowledge: string[];
  model: ModelConfig;
}

export interface TeamDetail {
  id: string;
  name: string;
  description: string;
  members: TeamMember[];
  teamWorkspaces: WorkspaceBinding[];
  teamKnowledge: string[];
  model?: ModelConfig;
}

export interface WorkflowDetail {
  id: string;
  name: string;
  description: string;
  nodes: string[];
  trigger: string;
  outputs: string[];
}

export interface ScheduleSummary {
  id: string;
  name: string;
  enabled: boolean;
  workerId: string;
  workerName?: string | null;
  prompt: string;
  sessionTitleTemplate?: string | null;
  workspaces?: string[] | null;
  triggerType: 'daily' | 'weekly';
  time: string;
  weekdays?: number[];
  timezone: string;
  misfirePolicy: 'skip' | 'run_once';
  createNewSession: boolean;
  lastRunAt?: string | null;
  nextRunAt?: string | null;
  lastStatus?: 'idle' | 'success' | 'failed' | 'running';
  lastError?: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface ScheduleRun {
  id: string;
  scheduleId: string;
  workerId: string;
  sessionId?: string | null;
  plannedAt: string;
  startedAt?: string | null;
  finishedAt?: string | null;
  status: 'running' | 'success' | 'failed' | 'skipped';
  error?: string | null;
  outputPreview?: string | null;
}

export interface ChannelSummary {
  id: string;
  platform: string;
  name: string;
  enabled: boolean;
  worker_id: string;
  config: Record<string, unknown>;
  status?: string;
  detail?: string;
}

export interface ChannelPlatform {
  id: string;
  name: string;
  available: boolean;
}
