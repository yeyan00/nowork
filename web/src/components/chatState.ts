import type { ChatMessage, MemberActivitiesByRun, MemberActivity, SessionSummary, TokenUsage } from '../types';
export type { MemberActivitiesByRun } from '../types';

export interface LiveTokenUsage {
  context: number;   // current context size (input_tokens)
  output: number;    // latest output tokens
}

export interface CachedSessionState {
  sessionId: string;
  messages: ChatMessage[];
  draft: string;
  tokenUsage: TokenUsage;
  liveTokenUsage: LiveTokenUsage | null;
  isLoading: boolean;
  isLoadingMore: boolean;
  hasMore: boolean;
  isStreaming: boolean;
  runId: string | null;
  error: string | null;
  loaded: boolean;
  lastActiveAt: number;
  memberActivitiesByRun: MemberActivitiesByRun[];
}

export interface CachedWorkerState {
  workerId: string;
  sessions: SessionSummary[];
  activeSessionId: string | null;
  sessionsLoaded: boolean;
  sessionStates: Record<string, CachedSessionState>;
}

export function createEmptyWorkerState(workerId: string): CachedWorkerState {
  return {
    workerId,
    sessions: [],
    activeSessionId: null,
    sessionsLoaded: false,
    sessionStates: {},
  };
}

export function ensureSessionState(workerState: CachedWorkerState, sessionId: string): CachedSessionState {
  if (!workerState.sessionStates[sessionId]) {
    workerState.sessionStates[sessionId] = {
      sessionId,
      messages: [],
      draft: '',
      tokenUsage: { input: 0, output: 0, total: 0, duration: 0 },
      liveTokenUsage: null,
      isLoading: false,
      isLoadingMore: false,
      hasMore: false,
      isStreaming: false,
      runId: null,
      error: null,
      loaded: false,
      lastActiveAt: 0,
      memberActivitiesByRun: [],
    };
  }

  return workerState.sessionStates[sessionId];
}

export function getVisibleAndOverflowSessionIds(workerState: CachedWorkerState): { visibleIds: string[]; overflowIds: string[] } {
  const rankedIds = workerState.sessions
    .map((session) => ({ id: session.id, score: workerState.sessionStates[session.id]?.lastActiveAt ?? 0 }))
    .sort((a, b) => b.score - a.score)
    .map((item) => item.id);

  const activeId = workerState.activeSessionId;
  const orderedIds = activeId ? [activeId, ...rankedIds.filter((id) => id !== activeId)] : rankedIds;
  const visibleIds = orderedIds.slice(0, 5);
  const overflowIds = orderedIds.filter((id) => !visibleIds.includes(id));

  return { visibleIds, overflowIds };
}

export function getRunningWorkerIds(states: Record<string, CachedWorkerState>): Set<string> {
  return new Set(
    Object.entries(states)
      .filter(([, workerState]) => Object.values(workerState.sessionStates).some((session) => session.isStreaming))
      .map(([workerId]) => workerId),
  );
}
