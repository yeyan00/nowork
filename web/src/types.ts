export type WorkerType = 'Agent' | 'Team' | 'Workflow';

export type AppPage =
  | 'Chat'
  | 'Workers'
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
  tokenInput?: number;
  tokenOutput?: number;
  toolCalls?: ToolCall[];
  reasoning?: string;
  streaming?: boolean;
  senderName?: string;
}

export interface SessionSummary {
  id: string;
  workerId: string;
  title: string;
  workspaces?: string[] | null;
  createdAt: string;
  updatedAt?: string;
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
