import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useI18n } from '../i18n';
import { cancelRun, cloneSession, compactSession, continueRunStream, createSession, exportSessionContext, getSessionSegments, listMessages, listModels, listSessions, sendMessageStream, updateSession } from '../lib/backend';
import type { AgentEvent, ContinueRunParams, ProviderInfo, SessionSegment } from '../lib/backend';
import type { ChatAttachment, ChatMessage, MemberActivity, PreviewingFile, ToolApprovalItem, ToolCall, WorkerSummary, WorkspaceBinding, WorkspaceInfo } from '../types';
import { FilePreviewSidebar } from './FilePreviewSidebar';
import { notifyWorkerDone } from '../lib/notify';
import type { CachedSessionState, CachedWorkerState } from './chatState';
import { createEmptyWorkerState, ensureSessionState, getVisibleAndOverflowSessionIds, type MemberActivitiesByRun } from './chatState';
import { MarkdownContent } from './MarkdownContent';
import { ToolCallList } from './ToolCallPanel';
import { ReasoningPanel } from './ReasoningPanel';
import { WorkerSettingsSidebar } from './WorkerSettingsSidebar';

interface ChatWorkspaceProps {
  worker: WorkerSummary | null;
  chatStates: Record<string, CachedWorkerState>;
  onChatStatesChange: React.Dispatch<React.SetStateAction<Record<string, CachedWorkerState>>>;
  requestedSessionId?: string | null;
  onRequestedSessionHandled?: () => void;
}

const DRAFT_SESSION_ID = '__draft__';

function formatContextWindowK(ctx: number): string {
  if (ctx >= 1000) {
    const k = ctx / 1000;
    return k >= 1000 ? `${(k / 1000).toFixed(1)}M` : `${Math.round(k)}K`;
  }
  return ctx.toLocaleString();
}

function formatContextUsage(contextTokens: number, contextWindow?: number): string {
  if (contextWindow && contextWindow > 0) {
    const pct = (contextTokens / contextWindow) * 100;
    return `${pct.toFixed(1)}%/${formatContextWindowK(contextWindow)}`;
  }
  return contextTokens.toLocaleString();
}

function formatSessionTime(timeStr: string, newSessionLabel: string): string {
  if (!timeStr) return newSessionLabel;
  try {
    let d: Date;
    const num = Number(timeStr);
    if (!Number.isNaN(num) && num > 0) {
      d = new Date(num > 1e12 ? num : num * 1000);
    } else {
      d = new Date(timeStr);
    }
    if (Number.isNaN(d.getTime())) return newSessionLabel;
    const pad = (n: number) => String(n).padStart(2, '0');
    const yy = String(d.getFullYear()).slice(-2);
    return `${yy}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  } catch {
    return newSessionLabel;
  }
}

function createSessionState(sessionId: string): CachedSessionState {
  return {
    sessionId,
    messages: [],
    draft: '',
    tokenUsage: { input: 0, output: 0, total: 0, duration: 0 },
    liveTokenUsage: null,
    totalInputTokens: 0,
    totalOutputTokens: 0,
    isLoading: false,
    isLoadingMore: false,
    hasMore: false,
    isStreaming: false,
    runId: null,
    error: null,
    loaded: false,
    lastActiveAt: 0,
    memberActivitiesByRun: [],
    compactedSegments: 0,
    isCompacting: false,
    pendingApproval: null,
  };
}

function cloneMessages(messages: ChatMessage[]): ChatMessage[] {
  return messages.map((message) => ({
    ...message,
    toolCalls: message.toolCalls ? [...message.toolCalls] : undefined,
  }));
}

function cloneWorkerState(workerState: CachedWorkerState): CachedWorkerState {
  return {
    ...workerState,
    sessions: [...workerState.sessions],
    sessionStates: Object.fromEntries(
      Object.entries(workerState.sessionStates).map(([sessionId, sessionState]) => [
        sessionId,
        {
          ...sessionState,
          messages: cloneMessages(sessionState.messages),
          tokenUsage: { ...sessionState.tokenUsage },
          liveTokenUsage: sessionState.liveTokenUsage ? { ...sessionState.liveTokenUsage } : null,
          totalInputTokens: sessionState.totalInputTokens ?? 0,
          totalOutputTokens: sessionState.totalOutputTokens ?? 0,
        },
      ]),
    ),
  };
}

function getWorkerWorkspaces(worker: WorkerSummary | null): WorkspaceBinding[] {
  const raw = worker?.config?.['workspaces'];
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((entry): entry is Record<string, unknown> => typeof entry === 'object' && entry !== null)
    .map((entry): WorkspaceBinding => ({
      path: String(entry.path ?? ''),
      permission: entry.permission === 'read' ? 'read' : 'read-write',
    }))
    .filter((entry) => entry.path.trim().length > 0);
}

function getWorkerCapabilities(worker: WorkerSummary | null): { file: boolean; image: boolean; video: boolean } {
  const raw = worker?.config?.['modelCapabilities'];
  if (!raw || typeof raw !== 'object') {
    return { file: true, image: false, video: false };
  }
  const caps = raw as Record<string, unknown>;
  return {
    file: caps.file !== false,
    image: caps.image === true,
    video: caps.video === true,
  };
}

function getAttachmentName(path: string): string {
  return path.replace(/\\/g, '/').split('/').filter(Boolean).pop() || path;
}

function getAttachmentKindLabel(kind: ChatAttachment['kind'], t: (key: string) => string): string {
  return kind === 'image' ? t('chat.attachmentImage') : kind === 'video' ? t('chat.attachmentVideo') : t('chat.attachmentFile');
}

function formatUserDisplayContent(content: string, attachments: ChatAttachment[], t: (key: string) => string): string {
  if (attachments.length === 0) return content;
  const lines = content ? [content, '', '[Attachments]'] : ['[Attachments]'];
  for (const item of attachments) {
    lines.push(`- ${getAttachmentKindLabel(item.kind, t)}: ${item.name}`);
  }
  return lines.join('\n');
}

async function pickLocalPaths(kind: ChatAttachment['kind']): Promise<string[]> {
  const invoke = (window as { __TAURI_INTERNALS__?: { invoke?: (cmd: string, args?: Record<string, unknown>) => Promise<string[] | string | null> } }).__TAURI_INTERNALS__?.invoke;
  if (invoke) {
    const result = await invoke('open_attachment_dialog', { kind, multiple: true });
    if (Array.isArray(result)) return result.filter((item): item is string => typeof item === 'string' && item.length > 0);
    if (typeof result === 'string' && result) return [result];
    return [];
  }

  const input = window.prompt(`Enter ${kind} path(s), separated by |`, '');
  if (!input) return [];
  return input.split('|').map((item) => item.trim()).filter(Boolean);
}

export function ChatWorkspace({ worker, chatStates, onChatStatesChange, requestedSessionId, onRequestedSessionHandled }: ChatWorkspaceProps) {
  const { t } = useI18n();
  const [showSessionList, setShowSessionList] = useState(false);
  const [showWorkerSettings, setShowWorkerSettings] = useState(false);
  const [showMemberSidebar, setShowMemberSidebar] = useState(false);
  const [showWsDropdown, setShowWsDropdown] = useState(false);
  const [showFilePreviewSidebar, setShowFilePreviewSidebar] = useState(false);
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [editingSessionTitle, setEditingSessionTitle] = useState('');
  const [contextMenu, setContextMenu] = useState<{ sessionId: string; x: number; y: number } | null>(null);

  // Close context menu on click outside or ESC
  useEffect(() => {
    if (!contextMenu) return;

    const handleClick = () => setContextMenu(null);
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setContextMenu(null);
    };

    document.addEventListener('click', handleClick);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('click', handleClick);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [contextMenu]);
  const [pendingPreviewFile, setPendingPreviewFile] = useState<PreviewingFile | null>(null);
  const [previewFileHandled, setPreviewFileHandled] = useState(true);
  const [pendingSessionWorkspaces, setPendingSessionWorkspaces] = useState<Record<string, string>>({});
  const [draftAttachments, setDraftAttachments] = useState<Record<string, ChatAttachment[]>>({});
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [defaultModelRef, setDefaultModelRef] = useState('');
  const [isListening, setIsListening] = useState(false);
  const [showCompactionHistory, setShowCompactionHistory] = useState(false);
  const [compactionSegments, setCompactionSegments] = useState<SessionSegment[]>([]);
  const [showTotalMetrics, setShowTotalMetrics] = useState(false);
  const messageListRef = useRef<HTMLDivElement>(null);
  const speechRef = useRef<{ recognition: SpeechRecognition; preamble: string } | null>(null);

  const updateWorkerState = useCallback((workerId: string, updater: (workerState: CachedWorkerState) => CachedWorkerState) => {
    onChatStatesChange((current) => {
      const baseState = current[workerId] ? cloneWorkerState(current[workerId]) : createEmptyWorkerState(workerId);
      return {
        ...current,
        [workerId]: updater(baseState),
      };
    });
  }, [onChatStatesChange]);

  const updateSessionState = useCallback((workerId: string, sessionId: string, updater: (sessionState: CachedSessionState) => CachedSessionState) => {
    updateWorkerState(workerId, (workerState) => {
      const sessionState = workerState.sessionStates[sessionId]
        ? {
            ...workerState.sessionStates[sessionId],
            messages: cloneMessages(workerState.sessionStates[sessionId].messages),
            tokenUsage: { ...workerState.sessionStates[sessionId].tokenUsage },
            liveTokenUsage: workerState.sessionStates[sessionId].liveTokenUsage ? { ...workerState.sessionStates[sessionId].liveTokenUsage } : null,
          }
        : createSessionState(sessionId);
      workerState.sessionStates = {
        ...workerState.sessionStates,
        [sessionId]: updater(sessionState),
      };
      return workerState;
    });
  }, [updateWorkerState]);

  const activateSession = useCallback((workerId: string, sessionId: string) => {
    updateWorkerState(workerId, (workerState) => {
      const sessionState = ensureSessionState(workerState, sessionId);
      sessionState.lastActiveAt = Date.now();
      workerState.activeSessionId = sessionId;
      return workerState;
    });
  }, [updateWorkerState]);

  const currentWorkerState = useMemo(() => {
    if (!worker) return null;
    return chatStates[worker.id] ?? createEmptyWorkerState(worker.id);
  }, [chatStates, worker]);

  const activeSessionId = currentWorkerState?.activeSessionId ?? null;
  const currentSessionState = activeSessionId && currentWorkerState
    ? currentWorkerState.sessionStates[activeSessionId] ?? createSessionState(activeSessionId)
    : null;
  const isStreaming = currentSessionState?.isStreaming === true;
  const composerSessionId = activeSessionId ?? DRAFT_SESSION_ID;
  const composerSessionState = currentWorkerState
    ? currentWorkerState.sessionStates[composerSessionId] ?? createSessionState(composerSessionId)
    : createSessionState(DRAFT_SESSION_ID);
  const currentSession = currentWorkerState?.sessions.find((session) => session.id === activeSessionId) ?? null;

  // Reset compaction history when switching sessions
  useEffect(() => {
    setShowCompactionHistory(false);
    setCompactionSegments([]);
  }, [activeSessionId]);

  const workerWorkspaces = useMemo(() => getWorkerWorkspaces(worker), [worker]);
  const workerDefaultModelRef = useMemo(() => {
    const cfg = worker?.config as Record<string, unknown> | undefined;
    return typeof cfg?.model === 'string' ? cfg.model : '';
  }, [worker]);
  const selectedModelRef = currentSession?.modelOverride ?? (workerDefaultModelRef || defaultModelRef);
  const selectedModelLabel = useMemo(() => {
    for (const provider of providers) {
      const model = provider.models.find((m) => m.id === selectedModelRef);
      if (model) return model.name;
    }
    return selectedModelRef || '';
  }, [providers, selectedModelRef]);

  const selectedModelContextWindow = useMemo(() => {
    for (const provider of providers) {
      const model = provider.models.find((m) => m.id === selectedModelRef);
      if (model?.contextWindow) return model.contextWindow;
    }
    return 128000;
  }, [providers, selectedModelRef]);

  /** Compute the effective set of workspace paths for the current context. */
  const effectiveWorkspaces = useMemo((): string[] => {
    // Priority: session's persisted workspaces > pending draft selection > all worker workspaces
    if (currentSession?.workspaces && currentSession.workspaces.length > 0) {
      return currentSession.workspaces;
    }
    if (worker && pendingSessionWorkspaces[worker.id]) {
      return pendingSessionWorkspaces[worker.id].split(',').filter(Boolean);
    }
    return workerWorkspaces.map((ws) => ws.path);
  }, [currentSession?.workspaces, pendingSessionWorkspaces, worker, workerWorkspaces]);

  const allWorkspacePaths = useMemo(() => workerWorkspaces.map((ws) => ws.path), [workerWorkspaces]);
  const workerCapabilities = useMemo(() => getWorkerCapabilities(worker), [worker]);

  // Workspace info for FilePreviewSidebar
  const workspaceInfos: WorkspaceInfo[] = useMemo(
    () => workerWorkspaces.map(ws => ({
      path: ws.path,
      name: ws.path.replace(/\\/g, '/').split('/').filter(Boolean).pop() || ws.path,
      permission: ws.permission,
    })),
    [workerWorkspaces],
  );

  const handlePreviewFile = useCallback((file: PreviewingFile) => {
    setPendingPreviewFile(file);
    setPreviewFileHandled(false);
    if (!showFilePreviewSidebar) {
      setShowFilePreviewSidebar(true);
    }
  }, [showFilePreviewSidebar]);

  const handlePreviewFileHandled = useCallback(() => {
    setPreviewFileHandled(true);
  }, []);

  const attachmentDraftKey = worker ? `${worker.id}:${composerSessionId}` : DRAFT_SESSION_ID;
  const composerAttachments = draftAttachments[attachmentDraftKey] ?? [];

  /** Directory-only name for display. */
  function wsLabel(path: string): string {
    return path.replace(/\\/g, '/').split('/').filter(Boolean).pop() || path;
  }

  useEffect(() => {
    if (!worker) return;
    if (currentWorkerState?.sessionsLoaded) return;

    let cancelled = false;

    void listSessions(worker.id)
      .then((nextSessions) => {
        if (cancelled) return;
        updateWorkerState(worker.id, (workerState) => {
          workerState.sessions = nextSessions;
          workerState.sessionsLoaded = true;
          if (!workerState.activeSessionId) {
            workerState.activeSessionId = nextSessions[0]?.id ?? null;
          }
          // Restore isStreaming state for sessions with a running run (e.g. after page refresh)
          for (const s of nextSessions) {
            if (s.hasRunningRun) {
              workerState.sessionStates[s.id] = {
                ...(workerState.sessionStates[s.id] ?? createSessionState(s.id)),
                isStreaming: true,
                lastActiveAt: Date.now(),
              };
            }
            // Initialize cumulative tokens from DB (if available)
            if (s.totalInputTokens !== undefined || s.totalOutputTokens !== undefined) {
              const existing = workerState.sessionStates[s.id];
              if (existing) {
                existing.totalInputTokens = s.totalInputTokens ?? existing.totalInputTokens;
                existing.totalOutputTokens = s.totalOutputTokens ?? existing.totalOutputTokens;
              } else {
                workerState.sessionStates[s.id] = {
                  ...createSessionState(s.id),
                  totalInputTokens: s.totalInputTokens ?? 0,
                  totalOutputTokens: s.totalOutputTokens ?? 0,
                };
              }
            }
          }
          return workerState;
        });
      })
      .catch(() => {
        if (cancelled) return;
        updateSessionState(worker.id, composerSessionId, (sessionState) => ({
          ...sessionState,
          error: 'Failed to load sessions',
        }));
      });

    return () => {
      cancelled = true;
    };
  }, [composerSessionId, currentWorkerState?.sessionsLoaded, updateSessionState, updateWorkerState, worker]);

  // Poll for running-run completion: when any session has isStreaming=true (e.g. restored after
  // page refresh while a background run is in progress), periodically check listSessions to
  // detect when the run finishes so we can re-enable the input and refresh messages.
  const hasAnyStreaming = Object.values(currentWorkerState?.sessionStates ?? {}).some((s) => s.isStreaming);

  useEffect(() => {
    if (!worker || !hasAnyStreaming) return;

    const interval = setInterval(() => {
      void listSessions(worker.id).then((sessions) => {
        updateWorkerState(worker.id, (ws) => {
          let changed = false;
          for (const s of sessions) {
            if (!s.hasRunningRun) {
              const ss = ws.sessionStates[s.id];
              // Only update if this session was restored from server (not locally streaming from a fresh send)
              // Locally streaming sessions have loaded=true; restored sessions have loaded=false initially
              if (ss?.isStreaming && ss.loaded !== true) {
                ws.sessionStates[s.id] = { ...ss, isStreaming: false, runId: null, loaded: false };
                changed = true;
              }
            }
          }
          if (changed) {
            ws.sessions = sessions;
          }
          return ws;
        });
      }).catch(() => {
        // Silently ignore polling errors
      });
    }, 3000);

    return () => clearInterval(interval);
  }, [hasAnyStreaming, updateWorkerState, worker]);

  useEffect(() => {
    if (!worker || !requestedSessionId || !currentWorkerState?.sessionsLoaded) return;
    const hasSession = currentWorkerState.sessions.some((session) => session.id === requestedSessionId);
    if (!hasSession) return;
    if (currentWorkerState.activeSessionId !== requestedSessionId) {
      activateSession(worker.id, requestedSessionId);
    }
    onRequestedSessionHandled?.();
  }, [activateSession, currentWorkerState?.activeSessionId, currentWorkerState?.sessions, currentWorkerState?.sessionsLoaded, onRequestedSessionHandled, requestedSessionId, worker]);

  useEffect(() => {
    let cancelled = false;
    void listModels().then((data) => {
      if (cancelled) return;
      setProviders(data.providers);
      setDefaultModelRef(data.default_model || '');
    }).catch(() => {
      if (cancelled) return;
      setProviders([]);
      setDefaultModelRef('');
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const PAGE_SIZE = 20;

  useEffect(() => {
    if (!worker || !activeSessionId) return;
    if (currentSessionState?.loaded) return;

    let cancelled = false;
    updateSessionState(worker.id, activeSessionId, (sessionState) => ({
      ...sessionState,
      isLoading: true,
      error: null,
    }));

    void listMessages(activeSessionId, PAGE_SIZE, 0)
      .then((result) => {
        if (cancelled) return;
        updateSessionState(worker.id, activeSessionId, (sessionState) => ({
          ...sessionState,
          messages: result.messages,
          loaded: true,
          isLoading: false,
          hasMore: result.has_more,
          memberActivitiesByRun: result.memberActivitiesByRun || [],
          compactedSegments: result.compactedSegments || 0,
          // Initialize cumulative tokens from DB (if not already set by streaming)
          totalInputTokens: sessionState.totalInputTokens || result.totalInputTokens || 0,
          totalOutputTokens: sessionState.totalOutputTokens || result.totalOutputTokens || 0,
        }));
      })
      .catch(() => {
        if (cancelled) return;
        updateSessionState(worker.id, activeSessionId, (sessionState) => ({
          ...sessionState,
          isLoading: false,
          error: 'Failed to load messages',
        }));
      });

    return () => {
      cancelled = true;
    };
  }, [activeSessionId, currentSessionState?.loaded, updateSessionState, worker]);

  const isUserAtBottom = useRef(true);

  const handleMessageListScroll = useCallback(() => {
    const el = messageListRef.current;
    if (!el) return;
    isUserAtBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
  }, []);

  useEffect(() => {
    const el = messageListRef.current;
    if (!el || !isUserAtBottom.current) return;
    requestAnimationFrame(() => {
      if (!messageListRef.current || !isUserAtBottom.current) return;
      messageListRef.current.scrollTop = messageListRef.current.scrollHeight;
    });
  }, [currentSessionState?.messages]);

  const sentinelRef = useRef<HTMLDivElement>(null);

  const handleLoadMore = useCallback(() => {
    if (!worker || !activeSessionId) return;
    const sessionState = currentWorkerState?.sessionStates[activeSessionId];
    if (!sessionState || sessionState.isLoadingMore || !sessionState.hasMore) return;

    const offset = sessionState.messages.length;
    updateSessionState(worker.id, activeSessionId, (s) => ({ ...s, isLoadingMore: true }));

    const el = messageListRef.current;
    const prevHeight = el ? el.scrollHeight : 0;

    void listMessages(activeSessionId, PAGE_SIZE, offset)
      .then((result) => {
        if (!messageListRef.current) return;
        updateSessionState(worker.id, activeSessionId, (s) => ({
          ...s,
          messages: [...result.messages, ...s.messages],
          hasMore: result.has_more,
          isLoadingMore: false,
        }));
        requestAnimationFrame(() => {
          if (messageListRef.current) {
            messageListRef.current.scrollTop = messageListRef.current.scrollHeight - prevHeight;
          }
        });
      })
      .catch(() => {
        updateSessionState(worker.id, activeSessionId, (s) => ({ ...s, isLoadingMore: false }));
      });
  }, [activeSessionId, currentWorkerState, updateSessionState, worker]);

  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel) return;
    const observer = new IntersectionObserver(
      (entries) => { if (entries[0]?.isIntersecting) handleLoadMore(); },
      { root: messageListRef.current, threshold: 0 },
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [handleLoadMore]);

  const handleCreateSession = useCallback(async () => {
    if (!worker) return;

    const nextSession = await createSession(worker.id, '', effectiveWorkspaces);
    updateWorkerState(worker.id, (workerState) => {
      workerState.sessions = [nextSession, ...workerState.sessions];
      workerState.activeSessionId = nextSession.id;
      workerState.sessionStates = {
        ...workerState.sessionStates,
        [nextSession.id]: {
          ...createSessionState(nextSession.id),
          loaded: true,
          lastActiveAt: Date.now(),
        },
      };
      return workerState;
    });
    setPendingSessionWorkspaces((current) => {
      const next = { ...current };
      delete next[worker.id];
      return next;
    });
  }, [allWorkspacePaths.length, effectiveWorkspaces, updateWorkerState, worker]);

  const handleCloneSession = useCallback(async (cloneFromRun?: number) => {
    if (!worker || !activeSessionId) return;

    const cloned = await cloneSession(activeSessionId, cloneFromRun);
    updateWorkerState(worker.id, (ws) => {
      ws.sessions = [cloned, ...ws.sessions];
      ws.activeSessionId = cloned.id;
      ws.sessionStates = {
        ...ws.sessionStates,
        [cloned.id]: {
          ...createSessionState(cloned.id),
          loaded: true,
          lastActiveAt: Date.now(),
        },
      };
      return ws;
    });
  }, [activeSessionId, updateWorkerState, worker]);

  const handleCompactSession = useCallback(async () => {
    if (!worker || !activeSessionId || isStreaming || currentSessionState?.isCompacting) return;

    const confirmed = window.confirm(t('chat.compactConfirm') || 'Compact this session? This will summarize old messages and may take a few seconds.');
    if (!confirmed) return;

    updateSessionState(worker.id, activeSessionId, (sessionState) => ({
      ...sessionState,
      isCompacting: true,
    }));
    try {
      await compactSession(activeSessionId);
      const result = await listMessages(activeSessionId, PAGE_SIZE, 0);
      updateSessionState(worker.id, activeSessionId, (sessionState) => ({
        ...sessionState,
        messages: result.messages,
        hasMore: result.has_more,
        compactedSegments: result.compactedSegments || 0,
        memberActivitiesByRun: result.memberActivitiesByRun || [],
        isCompacting: false,
      }));
    } catch {
      updateSessionState(worker.id, activeSessionId, (sessionState) => ({
        ...sessionState,
        isCompacting: false,
      }));
    }
  }, [activeSessionId, isStreaming, updateSessionState, worker]);

  const handleWorkspaceToggle = useCallback((path: string, checked: boolean) => {
    if (!worker) return;

    const computeNext = (current: string[]): string[] => {
      if (checked) {
        return current.includes(path) ? current : [...current, path];
      }
      const next = current.filter((p) => p !== path);
      return next.length === 0 ? allWorkspacePaths : next; // prevent empty selection
    };

    if (!activeSessionId || !currentSession) {
      // Draft mode: update pending selection
      setPendingSessionWorkspaces((prev) => {
        const current = prev[worker.id] ? prev[worker.id].split(',') : allWorkspacePaths;
        return { ...prev, [worker.id]: computeNext(current).join(',') };
      });
      return;
    }

    // Existing session: toggle and persist
    const currentList = currentSession.workspaces ?? allWorkspacePaths;
    const nextList = computeNext(currentList);

    const previousWorkspaces = currentSession.workspaces ?? null;
    updateWorkerState(worker.id, (workerState) => {
      workerState.sessions = workerState.sessions.map((session) => (
        session.id === activeSessionId
          ? { ...session, workspaces: nextList.length < allWorkspacePaths.length ? nextList : null }
          : session
      ));
      return workerState;
    });

    void updateSession(activeSessionId, {
      workspaces: nextList.length < allWorkspacePaths.length ? nextList : null,
    }).catch(() => {
      updateWorkerState(worker.id, (workerState) => {
        workerState.sessions = workerState.sessions.map((session) => (
          session.id === activeSessionId ? { ...session, workspaces: previousWorkspaces } : session
        ));
        return workerState;
      });
      updateSessionState(worker.id, activeSessionId, (sessionState) => ({
        ...sessionState,
        error: 'Failed to update workspace',
      }));
    });
  }, [activeSessionId, allWorkspacePaths, currentSession, updateSessionState, updateWorkerState, worker]);

  const handleModelChange = useCallback((nextValue: string) => {
    if (!worker || !activeSessionId || !currentSession || isStreaming) return;

    const baselineModelRef = workerDefaultModelRef || defaultModelRef;
    const nextOverride = nextValue && nextValue !== baselineModelRef ? nextValue : null;
    const previousOverride = currentSession.modelOverride ?? null;

    updateWorkerState(worker.id, (workerState) => {
      workerState.sessions = workerState.sessions.map((session) => (
        session.id === activeSessionId
          ? { ...session, modelOverride: nextOverride }
          : session
      ));
      return workerState;
    });

    void updateSession(activeSessionId, { modelOverride: nextOverride }).catch(() => {
      updateWorkerState(worker.id, (workerState) => {
        workerState.sessions = workerState.sessions.map((session) => (
          session.id === activeSessionId ? { ...session, modelOverride: previousOverride } : session
        ));
        return workerState;
      });
      updateSessionState(worker.id, activeSessionId, (sessionState) => ({
        ...sessionState,
        error: 'Failed to update model',
      }));
    });
  }, [activeSessionId, currentSession, defaultModelRef, isStreaming, updateSessionState, updateWorkerState, worker, workerDefaultModelRef]);

  const handleLearningToggle = useCallback((enabled: boolean) => {
    if (!worker || !activeSessionId || !currentSession || isStreaming) return;

    // enabled=true means follow worker default (null), enabled=false means explicitly off
    const nextValue = enabled ? null : false;
    const previousValue = currentSession.learningEnabled ?? null;

    updateWorkerState(worker.id, (workerState) => {
      workerState.sessions = workerState.sessions.map((session) => (
        session.id === activeSessionId
          ? { ...session, learningEnabled: nextValue }
          : session
      ));
      return workerState;
    });

    void updateSession(activeSessionId, { learningEnabled: nextValue }).catch(() => {
      updateWorkerState(worker.id, (workerState) => {
        workerState.sessions = workerState.sessions.map((session) => (
          session.id === activeSessionId ? { ...session, learningEnabled: previousValue } : session
        ));
        return workerState;
      });
    });
  }, [activeSessionId, currentSession, isStreaming, updateWorkerState, worker]);

  const addAttachments = useCallback(async (kind: ChatAttachment['kind']) => {
    if (!worker) return;
    const paths = await pickLocalPaths(kind);
    if (paths.length === 0) return;

    const additions = paths.map((path, index) => ({
      id: `${kind}-${Date.now()}-${index}`,
      kind,
      path,
      name: getAttachmentName(path),
    } as ChatAttachment));

    setDraftAttachments((current) => {
      const existing = current[attachmentDraftKey] ?? [];
      const knownPaths = new Set(existing.map((item) => `${item.kind}:${item.path}`));
      const merged = [...existing, ...additions.filter((item) => !knownPaths.has(`${item.kind}:${item.path}`))];
      return { ...current, [attachmentDraftKey]: merged };
    });
  }, [attachmentDraftKey, worker]);

  const removeAttachment = useCallback((attachmentId: string) => {
    setDraftAttachments((current) => ({
      ...current,
      [attachmentDraftKey]: (current[attachmentDraftKey] ?? []).filter((item) => item.id !== attachmentId),
    }));
  }, [attachmentDraftKey]);

  const clearComposerAttachments = useCallback((key: string) => {
    setDraftAttachments((current) => {
      if (!current[key] || current[key].length === 0) return current;
      const next = { ...current };
      delete next[key];
      return next;
    });
  }, []);

  const speechSupported = useMemo(() => {
    if (typeof window === 'undefined') return false;
    return !!(window.SpeechRecognition || window.webkitSpeechRecognition);
  }, []);

  // Close ws dropdown on outside click
  useEffect(() => {
    if (!showWsDropdown) return;
    const handler = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      if (!target.closest('.composer-ws-dropdown-wrapper')) {
        setShowWsDropdown(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [showWsDropdown]);

  const toggleVoice = useCallback(() => {
    if (!worker) return;

    // Stop if already listening
    if (isListening && speechRef.current) {
      speechRef.current.recognition.stop();
      speechRef.current = null;
      setIsListening(false);
      return;
    }

    const SpeechRecognitionCtor = (window.SpeechRecognition || window.webkitSpeechRecognition) as typeof SpeechRecognition | undefined;
    if (!SpeechRecognitionCtor) return;

    const recognition = new SpeechRecognitionCtor();
    recognition.lang = navigator.language || 'zh-CN';
    recognition.continuous = true;
    recognition.interimResults = true;

    // Capture the text already in the textarea before we start appending
    const preamble = composerSessionState.draft ?? '';

    recognition.onresult = (event: SpeechRecognitionEvent) => {
      let finalText = '';
      let interimText = '';
      for (let i = 0; i < event.results.length; i++) {
        const result = event.results[i];
        if (result.isFinal) {
          finalText += result[0].transcript;
        } else {
          interimText += result[0].transcript;
        }
      }
      const combined = preamble + (preamble && !preamble.endsWith('\n') ? '\n' : '') + finalText + interimText;
      updateSessionState(worker.id, composerSessionId, (s) => ({ ...s, draft: combined }));
    };

    recognition.onerror = () => {
      setIsListening(false);
      speechRef.current = null;
    };

    recognition.onend = () => {
      setIsListening(false);
      speechRef.current = null;
    };

    speechRef.current = { recognition, preamble };
    setIsListening(true);
    recognition.start();
  }, [composerSessionId, composerSessionState.draft, isListening, updateSessionState, worker]);

  const handleSend = useCallback(async () => {
    if (!worker) return;

    const userContent = composerSessionState.draft.trim();
    if ((!userContent && composerAttachments.length === 0) || currentSessionState?.isStreaming) return;

    const outgoingAttachments = [...composerAttachments];
    const displayContent = formatUserDisplayContent(userContent, outgoingAttachments, t);
    const targetWorkerId = worker.id;
    let targetSessionId = activeSessionId ?? composerSessionId;
    const originalDraft = composerSessionState.draft;
    updateSessionState(targetWorkerId, composerSessionId, (sessionState) => ({
      ...sessionState,
      draft: '',
      error: null,
    }));
    clearComposerAttachments(attachmentDraftKey);

    try {
      let sessionId = activeSessionId;
      if (!sessionId) {
        const ws = effectiveWorkspaces.length > 0 && effectiveWorkspaces.length < allWorkspacePaths.length
          ? effectiveWorkspaces
          : null;
        const createdSession = await createSession(targetWorkerId, '', ws);
        sessionId = createdSession.id;
        setPendingSessionWorkspaces((current) => {
          const next = { ...current };
          delete next[targetWorkerId];
          return next;
        });
        updateWorkerState(targetWorkerId, (workerState) => {
          workerState.sessions = [createdSession, ...workerState.sessions];
          workerState.activeSessionId = createdSession.id;
          workerState.sessionStates = {
            ...workerState.sessionStates,
            [createdSession.id]: {
              ...createSessionState(createdSession.id),
              loaded: true,
              lastActiveAt: Date.now(),
            },
            [DRAFT_SESSION_ID]: {
              ...(workerState.sessionStates[DRAFT_SESSION_ID] ?? createSessionState(DRAFT_SESSION_ID)),
              draft: '',
            },
          };
          return workerState;
        });
      }
      targetSessionId = sessionId;

      const userMsgId = `user-${Date.now()}`;
      const workerMsgId = `worker-${Date.now()}`;

      const userMessage: ChatMessage = {
        id: userMsgId,
        role: 'user',
        content: displayContent,
      };

      const workerMessage: ChatMessage = {
        id: workerMsgId,
        role: 'worker',
        content: '',
        toolCalls: [],
        reasoning: '',
        streaming: true,
      };

      updateSessionState(targetWorkerId, sessionId, (sessionState) => ({
        ...sessionState,
        loaded: true,
        isStreaming: true,
        runId: null,
        error: null,
        lastActiveAt: Date.now(),
        messages: [...sessionState.messages, userMessage, workerMessage],
      }));

      let currentWorkerMsgId = workerMsgId;
      let accumulatedContent = '';
      let accumulatedReasoning = '';
      let accumulatedTools: ToolCall[] = [];
      let accumulatedSenderName = '';
      let liveInput = 0;
      let liveOutput = 0;
      let msgCounter = 0;

      // Determine which ModelRequestCompleted event to listen to:
      // - Agent worker → 'ModelRequestCompleted'
      // - Team worker  → 'TeamModelRequestCompleted' (ignore member events)
      const isTeamWorker = worker.type === 'Team';
      const contextEventName = isTeamWorker ? 'TeamModelRequestCompleted' : 'ModelRequestCompleted';

      await sendMessageStream(sessionId, userContent, outgoingAttachments, (event: AgentEvent) => {
        const eventType = event.event;

        if (event.run_id) {
          updateSessionState(targetWorkerId, sessionId!, (sessionState) => ({
            ...sessionState,
            runId: sessionState.runId ?? event.run_id ?? null,
          }));
        }

        // Live token tracking: show latest context size & output tokens
        // For Team workers, TeamModelRequestCompleted reflects orchestrator context size
        // For billing: accumulate ALL ModelRequestCompleted events (orchestrator + members)
        if (eventType === 'ModelRequestCompleted' || eventType === 'TeamModelRequestCompleted') {
          const m = event.metrics;
          if (m) {
            // Billing accumulation: sum of each API call's input/output tokens
            const inp = m.input_tokens ?? 0;
            const out = m.output_tokens ?? 0;
            updateSessionState(targetWorkerId, sessionId!, (sessionState) => ({
              ...sessionState,
              totalInputTokens: sessionState.totalInputTokens + inp,
              totalOutputTokens: sessionState.totalOutputTokens + out,
            }));
            // Live display: only use orchestrator event for Team workers
            if (eventType === contextEventName) {
              liveInput = inp;
              liveOutput = out;
              updateSessionState(targetWorkerId, sessionId!, (sessionState) => ({
                ...sessionState,
                liveTokenUsage: { context: liveInput, output: liveOutput },
              }));
            }
          }
          return;
        }

        if (eventType === 'ToolCallStarted' || eventType === 'ToolCallCompleted' || eventType === 'ToolCallError') {
          if (event.toolCalls) {
            // Backend sends a cumulative toolCalls list for the entire stream.
            // We track tools per-message: append on Started, update on Completed/Error.
            if (eventType === 'ToolCallStarted' && event.toolCalls.length > 0) {
              const newTool = event.toolCalls[event.toolCalls.length - 1];
              accumulatedTools = [...accumulatedTools, newTool];
            } else if (eventType === 'ToolCallCompleted' && event.toolCalls) {
              accumulatedTools = accumulatedTools.map(tc => {
                const updated = event.toolCalls!.find((t: ToolCall) => t.toolCallId === tc.toolCallId);
                return updated ? { ...tc, result: updated.result } : tc;
              });
            } else if (eventType === 'ToolCallError' && event.toolCalls) {
              accumulatedTools = accumulatedTools.map(tc => {
                const updated = event.toolCalls!.find((t: ToolCall) => t.toolCallId === tc.toolCallId);
                return updated ? { ...tc, error: updated.error } : tc;
              });
            }
          }

          updateSessionState(targetWorkerId, sessionId!, (sessionState) => ({
            ...sessionState,
            messages: sessionState.messages.map((message) => message.id === currentWorkerMsgId ? {
              id: currentWorkerMsgId,
              role: 'worker',
              content: accumulatedContent || '...',
              toolCalls: accumulatedTools,
              reasoning: accumulatedReasoning || undefined,
              streaming: true,
            } : message),
          }));
          return;
        }

        if (eventType === 'MemberAgentActivity') {
          // Incremental delta events — merge into local state
          const delta = event.delta as { type: string; agentId: string; [key: string]: unknown } | undefined;
          if (delta) {
            const runId = event.run_id || '';
            updateSessionState(targetWorkerId, sessionId!, (sessionState) => {
              const existing = sessionState.memberActivitiesByRun || [];
              const runIdx = existing.findIndex(r => r.runId === runId);
              let activities: MemberActivity[];

              if (runIdx >= 0) {
                activities = existing[runIdx].activities.map(a => ({ ...a, toolCalls: [...a.toolCalls] }));
              } else {
                activities = [];
              }

              // For non-started events, find the LAST running entry for this agentId
              // (same agent can be called multiple times; we want the active one)
              const findActiveAgentIdx = () => {
                for (let i = activities.length - 1; i >= 0; i--) {
                  if (activities[i].agentId === delta.agentId && activities[i].status === 'running') return i;
                }
                // Fallback: last entry with this agentId
                for (let i = activities.length - 1; i >= 0; i--) {
                  if (activities[i].agentId === delta.agentId) return i;
                }
                return -1;
              };

              let agentIdx: number;
              let agent: MemberActivity;

              switch (delta.type) {
                case 'member_started': {
                  // If an entry with same agentId exists and is completed/error,
                  // this is a new invocation — create a fresh entry
                  const prevIdx = activities.findIndex(a => a.agentId === delta.agentId);
                  if (prevIdx >= 0 && (activities[prevIdx].status === 'completed' || activities[prevIdx].status === 'error')) {
                    agentIdx = -1; // will append
                  } else if (prevIdx >= 0) {
                    agentIdx = prevIdx; // reuse running entry
                  } else {
                    agentIdx = -1; // first time, append
                  }
                  agent = agentIdx >= 0
                    ? { ...activities[agentIdx] }
                    : { agentName: (delta.agentName as string) || '', agentId: delta.agentId, status: 'running', toolCalls: [], content: '' };
                  agent.agentName = (delta.agentName as string) || agent.agentName;
                  agent.status = 'running';
                  break;
                }
                case 'member_completed': {
                  agentIdx = findActiveAgentIdx();
                  agent = agentIdx >= 0
                    ? { ...activities[agentIdx] }
                    : { agentName: '', agentId: delta.agentId, status: 'running', toolCalls: [], content: '' };
                  const newContent = delta.content as string | undefined;
                  if (newContent !== undefined) agent.content = newContent;
                  agent.status = delta.error ? 'error' : 'completed';
                  break;
                }
                case 'content': {
                  agentIdx = findActiveAgentIdx();
                  agent = agentIdx >= 0
                    ? { ...activities[agentIdx] }
                    : { agentName: '', agentId: delta.agentId, status: 'running', toolCalls: [], content: '' };
                  agent.content += (delta.content as string) || '';
                  break;
                }
                case 'tool_started': {
                  agentIdx = findActiveAgentIdx();
                  agent = agentIdx >= 0
                    ? { ...activities[agentIdx], toolCalls: [...activities[agentIdx].toolCalls] }
                    : { agentName: '', agentId: delta.agentId, status: 'running', toolCalls: [], content: '' };
                  agent.toolCalls.push(delta.toolCall as ToolCall);
                  break;
                }
                case 'tool_completed': {
                  agentIdx = findActiveAgentIdx();
                  agent = agentIdx >= 0
                    ? { ...activities[agentIdx], toolCalls: [...activities[agentIdx].toolCalls] }
                    : { agentName: '', agentId: delta.agentId, status: 'running', toolCalls: [], content: '' };
                  agent.toolCalls = agent.toolCalls.map(tc =>
                    tc.toolCallId === delta.toolCallId
                      ? { ...tc, result: delta.result, status: 'completed' as const }
                      : tc
                  );
                  break;
                }
                case 'tool_error': {
                  agentIdx = findActiveAgentIdx();
                  agent = agentIdx >= 0
                    ? { ...activities[agentIdx], toolCalls: [...activities[agentIdx].toolCalls] }
                    : { agentName: '', agentId: delta.agentId, status: 'running', toolCalls: [], content: '' };
                  agent.toolCalls = agent.toolCalls.map(tc =>
                    tc.toolCallId === delta.toolCallId
                      ? { ...tc, error: delta.error as string || 'Error', status: 'error' as const }
                      : tc
                  );
                  break;
                }
                default:
                  return sessionState;
              }

              if (agentIdx >= 0) {
                activities[agentIdx] = agent;
              } else {
                activities.push(agent);
              }

              let updated: MemberActivitiesByRun[];
              if (runIdx >= 0) {
                updated = [...existing];
                updated[runIdx] = { ...updated[runIdx], activities };
              } else {
                updated = [...existing, { runId, activities }];
              }
              return { ...sessionState, memberActivitiesByRun: updated };
            });
          }
          return;
        }

        if (eventType === 'RunContent') {
          const senderName = String(event.agent_name || event.team_name || '');
          if (senderName && !accumulatedSenderName) {
            accumulatedSenderName = senderName;
          }

          if (accumulatedTools.length > 0) {
            updateSessionState(targetWorkerId, sessionId!, (sessionState) => ({
              ...sessionState,
              messages: sessionState.messages.map((message) => message.id === currentWorkerMsgId ? {
                ...message,
                streaming: false,
              } : message),
            }));
            msgCounter += 1;
            currentWorkerMsgId = `worker-${Date.now()}-${msgCounter}`;
            accumulatedContent = '';
            accumulatedReasoning = '';
            accumulatedTools = [];
            const newMessage: ChatMessage = {
              id: currentWorkerMsgId,
              role: 'worker',
              content: '',
              streaming: true,
              senderName: senderName || accumulatedSenderName || undefined,
            };
            updateSessionState(targetWorkerId, sessionId!, (sessionState) => ({
              ...sessionState,
              messages: [...sessionState.messages, newMessage],
            }));
          }

          if (event.content) {
            accumulatedContent += event.content;
          }

          if (event.reasoning_content) {
            accumulatedReasoning += event.reasoning_content;
          }

          updateSessionState(targetWorkerId, sessionId!, (sessionState) => ({
            ...sessionState,
            messages: sessionState.messages.map((message) => message.id === currentWorkerMsgId ? {
              ...message,
              content: accumulatedContent,
              reasoning: accumulatedReasoning || undefined,
              senderName: accumulatedSenderName || undefined,
            } : message),
          }));
          return;
        }

        if (eventType === 'RunCompleted') {
          const senderName = String(event.agent_name || event.team_name || '') || accumulatedSenderName;
          if (event.content && event.content.length >= accumulatedContent.length) accumulatedContent = event.content;
          if (event.reasoning && event.reasoning.length >= accumulatedReasoning.length) accumulatedReasoning = event.reasoning;

          // Store last context size & output tokens on the message
          const finalContext = liveInput;
          const finalOutput = liveOutput;

          updateSessionState(targetWorkerId, sessionId!, (sessionState) => ({
            ...sessionState,
            isStreaming: false,
            runId: null,
            liveTokenUsage: null,
            messages: sessionState.messages.map((message) => message.id === currentWorkerMsgId ? {
              id: currentWorkerMsgId,
              role: 'worker',
              content: accumulatedContent,
              toolCalls: accumulatedTools,
              reasoning: accumulatedReasoning || undefined,
              streaming: false,
              senderName: senderName || undefined,
              contextSize: finalContext || undefined,
              outputTokens: finalOutput || undefined,
            } : message),
          }));
          // Send system notification when task completes and window is hidden
          if (document.hidden && worker?.name && userContent) {
            void notifyWorkerDone(worker.name, userContent);
          }
          return;
        }

        if (eventType === 'RunError') {
          updateSessionState(targetWorkerId, sessionId!, (sessionState) => ({
            ...sessionState,
            isStreaming: false,
            runId: null,
            messages: sessionState.messages.map((message) => message.id === currentWorkerMsgId ? {
              id: currentWorkerMsgId,
              role: 'worker',
              content: `Error: ${event.content ?? 'Unknown error'}`,
              streaming: false,
            } : message),
          }));
          return;
        }

        if (eventType === 'RunCancelled') {
          if (!accumulatedContent && event.content) accumulatedContent = event.content;
          updateSessionState(targetWorkerId, sessionId!, (sessionState) => ({
            ...sessionState,
            isStreaming: false,
            runId: null,
            messages: sessionState.messages.map((message) => message.id === currentWorkerMsgId ? {
              id: currentWorkerMsgId,
              role: 'worker',
              content: accumulatedContent || 'Cancelled',
              streaming: false,
            } : message),
          }));
        }

        if (eventType === 'ContextCompacted') {
          updateSessionState(targetWorkerId, sessionId!, (sessionState) => ({
            ...sessionState,
            compactedSegments: (sessionState.compactedSegments ?? 0) + 1,
            isCompacting: false,
          }));
        }

        if (eventType === 'CompactionStarted') {
          updateSessionState(targetWorkerId, sessionId!, (sessionState) => ({
            ...sessionState,
            isCompacting: true,
          }));
        }

        if (eventType === 'CompactionCompleted') {
          updateSessionState(targetWorkerId, sessionId!, (sessionState) => ({
            ...sessionState,
            isCompacting: false,
            compactedSegments: (sessionState.compactedSegments ?? 0) + 1,
          }));
        }

        if (eventType === 'CompactionSkipped') {
          updateSessionState(targetWorkerId, sessionId!, (sessionState) => ({
            ...sessionState,
            isCompacting: false,
          }));
        }

        if (eventType === 'CompactionFailed') {
          updateSessionState(targetWorkerId, sessionId!, (sessionState) => ({
            ...sessionState,
            isCompacting: false,
            error: t('chat.compactionFailed') || 'Context compression failed, consider starting a new session',
          }));
        }

        if (eventType === 'ToolApprovalRequest') {
          // Agent paused — needs user approval for a write operation outside base_dirs
          const approvals = (event.approvals || []) as ToolApprovalItem[];
          const runId = event.run_id as string || '';
          updateSessionState(targetWorkerId, sessionId!, (sessionState) => ({
            ...sessionState,
            pendingApproval: {
              runId,
              approvals,
            },
            // Keep isStreaming true — the run is paused, not completed
          }));
        }
      });
    } catch {
      updateSessionState(targetWorkerId, composerSessionId, (sessionState) => ({
        ...sessionState,
        draft: originalDraft,
      }));
      setDraftAttachments((current) => ({
        ...current,
        [attachmentDraftKey]: outgoingAttachments,
      }));
      updateSessionState(targetWorkerId, targetSessionId, (sessionState) => ({
        ...sessionState,
        isStreaming: false,
        runId: null,
        error: 'Failed to send message',
      }));
    }
  }, [activeSessionId, allWorkspacePaths.length, attachmentDraftKey, clearComposerAttachments, composerAttachments, composerSessionId, composerSessionState.draft, currentSessionState?.isStreaming, effectiveWorkspaces, updateSessionState, updateWorkerState, worker]);

  const handleCancel = useCallback(async () => {
    const currentRunId = currentSessionState?.runId;
    if (!currentRunId) return;
    try {
      await cancelRun(currentRunId);
    } catch {
      if (!worker || !activeSessionId) return;
      updateSessionState(worker.id, activeSessionId, (sessionState) => ({
        ...sessionState,
        error: 'Failed to cancel',
      }));
    }
  }, [activeSessionId, currentSessionState?.runId, updateSessionState, worker]);

  const handleApproval = useCallback(async (approved: boolean, alwaysAllowDir?: string) => {
    if (!worker || !activeSessionId) return;
    const pending = currentSessionState?.pendingApproval;
    if (!pending) return;

    // Clear the pending approval first
    updateSessionState(worker.id, activeSessionId, (sessionState) => ({
      ...sessionState,
      pendingApproval: null,
    }));

    if (!approved) {
      // Reject — send continue_run with confirmed=false
      try {
        await continueRunStream({
          runId: pending.runId,
          sessionId: activeSessionId,
          workerId: worker.id,
          confirmed: false,
          updatedTools: pending.approvals.map(a => ({
            toolCallId: a.toolCallId,
            toolName: a.toolName,
            toolArgs: a.toolArgs,
            requiresConfirmation: true,
          })),
        }, (event) => {
          // Process events from the rejected continue
          const eventType = event.event;
          if (eventType === 'RunCompleted' || eventType === 'RunError' || eventType === 'RunCancelled') {
            updateSessionState(worker.id, activeSessionId, (sessionState) => ({
              ...sessionState,
              isStreaming: false,
              runId: null,
            }));
          }
        });
      } catch {
        updateSessionState(worker.id, activeSessionId, (sessionState) => ({
          ...sessionState,
          isStreaming: false,
          runId: null,
        }));
      }
      return;
    }

    // Approved — send continue_run with confirmed=true
    try {
      let accumulatedContent = '';
      let accumulatedTools: ToolCall[] = [];

      await continueRunStream({
        runId: pending.runId,
        sessionId: activeSessionId,
        workerId: worker.id,
        confirmed: true,
        alwaysAllowDir,
        updatedTools: pending.approvals.map(a => ({
          toolCallId: a.toolCallId,
          toolName: a.toolName,
          toolArgs: a.toolArgs,
          requiresConfirmation: true,
        })),
      }, (event) => {
        const eventType = event.event;

        if (eventType === 'ContextCompacted') {
          updateSessionState(worker.id, activeSessionId, (sessionState) => ({
            ...sessionState,
            compactedSegments: (sessionState.compactedSegments ?? 0) + 1,
          }));
          return;
        }

        if (eventType === 'ToolApprovalRequest') {
          // Another approval needed during continue
          const approvals = (event.approvals || []) as ToolApprovalItem[];
          const runId = event.run_id as string || '';
          updateSessionState(worker.id, activeSessionId, (sessionState) => ({
            ...sessionState,
            pendingApproval: { runId, approvals },
          }));
          return;
        }

        if (eventType === 'ToolCallStarted' && event.toolCalls && event.toolCalls.length > 0) {
          const newTool = event.toolCalls[event.toolCalls.length - 1];
          accumulatedTools = [...accumulatedTools, newTool];
        } else if (eventType === 'ToolCallCompleted' && event.toolCalls) {
          accumulatedTools = accumulatedTools.map(tc => {
            const updated = event.toolCalls!.find((t: ToolCall) => t.toolCallId === tc.toolCallId);
            return updated ? { ...tc, result: updated.result } : tc;
          });
        }

        if (eventType === 'RunContent') {
          if (event.content) accumulatedContent += event.content;
          updateSessionState(worker.id, activeSessionId, (sessionState) => {
            const lastMsgIdx = sessionState.messages.length - 1;
            return {
              ...sessionState,
              messages: sessionState.messages.map((msg, idx) => idx === lastMsgIdx ? {
                ...msg,
                content: accumulatedContent,
                toolCalls: accumulatedTools.length > 0 ? accumulatedTools : msg.toolCalls,
              } : msg),
            };
          });
          return;
        }

        if (eventType === 'RunCompleted' || eventType === 'RunError' || eventType === 'RunCancelled') {
          if (event.content) accumulatedContent = event.content;
          updateSessionState(worker.id, activeSessionId, (sessionState) => {
            const lastMsgIdx = sessionState.messages.length - 1;
            return {
              ...sessionState,
              isStreaming: false,
              runId: null,
              messages: sessionState.messages.map((msg, idx) => idx === lastMsgIdx ? {
                ...msg,
                content: accumulatedContent || msg.content,
                toolCalls: accumulatedTools.length > 0 ? accumulatedTools : msg.toolCalls,
                streaming: false,
              } : msg),
            };
          });
          return;
        }
      });
    } catch {
      updateSessionState(worker.id, activeSessionId, (sessionState) => ({
        ...sessionState,
        isStreaming: false,
        runId: null,
      }));
    }
  }, [activeSessionId, currentSessionState?.pendingApproval, updateSessionState, worker]);

  if (!worker) {
    return <section className="chat-workspace">{t('chat.selectWorker')}</section>;
  }

  const messages = currentSessionState?.messages ?? [];
  const isLoading = !currentWorkerState?.sessionsLoaded || currentSessionState?.isLoading === true;
  const error = currentSessionState?.error ?? composerSessionState.error;
  const draft = composerSessionState.draft;
  const workerState = currentWorkerState ?? createEmptyWorkerState(worker.id);
  const { visibleIds, overflowIds } = getVisibleAndOverflowSessionIds(workerState);
  const visibleSessions = visibleIds
    .map((sessionId) => workerState.sessions.find((session) => session.id === sessionId))
    .filter((session): session is NonNullable<typeof session> => Boolean(session));
  const overflowSessions = overflowIds
    .map((sessionId) => workerState.sessions.find((session) => session.id === sessionId))
    .filter((session): session is NonNullable<typeof session> => Boolean(session));
  const sessionTitle = currentSession
    ? formatSessionTime(currentSession.updatedAt || currentSession.createdAt, t('chat.newSessionTitle'))
    : t('chat.newSessionTitle');

  return (
    <section className="chat-workspace">
      <header className="chat-header">
        <div className="chat-title-block">
          <div className="title-row">
            <h1>{worker.name}</h1>
            <span className={`worker-badge ${worker.type.toLowerCase()}`}>{worker.type}</span>
          </div>
          <p>{worker.description}</p>
        </div>

        <div className="header-actions">
          <button
            type="button"
            className={`icon-button tooltip${showFilePreviewSidebar ? ' active' : ''}`}
            aria-label={t('chat.toggleFilePreview') || 'Files'}
            title={showFilePreviewSidebar ? (t('chat.hideFilePreview') || 'Hide Files') : (t('chat.showFilePreview') || 'Show Files')}
            onClick={() => setShowFilePreviewSidebar((v) => !v)}
          >
            📁
          </button>
          {worker.type === 'Team' && (
            <button
              type="button"
              className={`icon-button tooltip member-toggle-btn${showMemberSidebar ? ' active' : ''}`}
              aria-label={t('chat.toggleMemberActivities')}
              title={showMemberSidebar ? t('chat.hideMemberActivities') : t('chat.showMemberActivities')}
              onClick={() => setShowMemberSidebar((v) => !v)}
            >
              <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><circle cx="7" cy="7" r="3"/><path d="M1 17v-1a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v1"/><circle cx="15" cy="7" r="2.5"/><path d="M15 11.5a3 3 0 0 1 3 3v.5"/></svg>
            </button>
          )}
          <button type="button" className="icon-button tooltip" aria-label={t('chat.newSession')} title={t('chat.newSession')} onClick={() => void handleCreateSession()}>
            <svg viewBox="0 0 20 20" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="10" y1="4" x2="10" y2="16"/><line x1="4" y1="10" x2="16" y2="10"/></svg>
          </button>
          <button type="button" className="gear-button tooltip" aria-label={t('chat.workerSettings')} title={t('chat.workerSettings')} onClick={() => setShowWorkerSettings((value) => !value)}>
            ⚙
          </button>
        </div>
      </header>

      <div className="chat-session-tabs" role="tablist" aria-label="Sessions">
        {visibleSessions.map((session) => {
          const sessionState = workerState.sessionStates[session.id];
          return (
            <button
              key={session.id}
              type="button"
              role="tab"
              aria-selected={session.id === activeSessionId}
              className={session.id === activeSessionId ? 'chat-session-tab active' : 'chat-session-tab'}
              onClick={() => activateSession(worker.id, session.id)}
              onDoubleClick={() => { setEditingSessionTitle(session.title && session.title !== 'Untitled' ? session.title : ''); setEditingSessionId(session.id); }}
              onContextMenu={(e) => {
                e.preventDefault();
                setContextMenu({ sessionId: session.id, x: e.clientX, y: e.clientY });
              }}
            >
              {editingSessionId === session.id ? (
                <input
                  type="text"
                  className="session-tab-rename-input"
                  value={editingSessionTitle}
                  onChange={(e) => setEditingSessionTitle(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.stopPropagation();
                      updateSession(session.id, { title: editingSessionTitle }).then((updated) => {
                        updateWorkerState(worker.id, (ws) => ({
                          ...ws,
                          sessions: ws.sessions.map((s) => s.id === session.id ? { ...s, title: updated.title } : s),
                        }));
                      }).catch(() => {}).finally(() => setEditingSessionId(null));
                    } else if (e.key === 'Escape') {
                      setEditingSessionId(null);
                    }
                  }}
                  onBlur={() => setEditingSessionId(null)}
                  autoFocus
                  onClick={(e) => e.stopPropagation()}
                />
              ) : (
                <span>{session.title && session.title !== 'Untitled' ? session.title : formatSessionTime(session.updatedAt || session.createdAt, t('chat.newSessionTitle'))}</span>
              )}
              {sessionState?.isStreaming && <span className="chat-session-running-dot" aria-hidden="true" />}
            </button>
          );
        })}
        {contextMenu && (
          <div
            className="context-menu"
            style={{ position: 'fixed', left: contextMenu.x, top: contextMenu.y, zIndex: 1000 }}
            onClick={(e) => e.stopPropagation()}
          >
            <button
              type="button"
              className="context-menu-item"
              onClick={() => {
                const session = visibleSessions.find(s => s.id === contextMenu.sessionId) || overflowSessions.find(s => s.id === contextMenu.sessionId);
                setEditingSessionTitle(session?.title && session.title !== 'Untitled' ? session.title : '');
                setEditingSessionId(contextMenu.sessionId);
                setContextMenu(null);
              }}
            >
              {t('chat.renameSession') || 'Rename'}
            </button>
            <button
              type="button"
              className="context-menu-item"
              onClick={() => {
                void handleCloneSession();
                setContextMenu(null);
              }}
            >
              {t('chat.cloneSession') || 'Clone'}
            </button>
            <button
              type="button"
              className="context-menu-item"
              disabled={isStreaming}
              onClick={() => {
                void handleCompactSession();
                setContextMenu(null);
              }}
            >
              {t('chat.compactSession') || 'Compact'}
            </button>
            <button
              type="button"
              className="context-menu-item"
              onClick={() => {
                const sessionId = contextMenu.sessionId;
                exportSessionContext(sessionId).then((markdown) => {
                  // Download as file
                  const blob = new Blob([markdown], { type: 'text/markdown' });
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement('a');
                  a.href = url;
                  a.download = `session-${sessionId.split(':').pop()}-context.md`;
                  a.click();
                  URL.revokeObjectURL(url);
                }).catch((err) => {
                  console.error('Failed to export context:', err);
                });
                setContextMenu(null);
              }}
            >
              {t('chat.exportContext') || 'Export Context'}
            </button>
          </div>
        )}
        {overflowSessions.length > 0 && (
          <div className="chat-session-overflow">
            <button
              type="button"
              className="icon-button"
              aria-label={t('chat.moreSessions')}
              onClick={() => setShowSessionList((value) => !value)}
            >
              {t('chat.more')}
            </button>
            {showSessionList && (
              <div className="session-dropdown">
                {overflowSessions.map((session) => {
                  const sessionState = workerState.sessionStates[session.id];
                  return (
                    <button
                      key={session.id}
                      type="button"
                      className={`session-dropdown-item ${session.id === activeSessionId ? 'active' : ''}`}
                      onClick={() => {
                        activateSession(worker.id, session.id);
                        setShowSessionList(false);
                      }}
                    >
                      <span>{session.title && session.title !== 'Untitled' ? session.title : formatSessionTime(session.updatedAt || session.createdAt, t('chat.newSessionTitle'))}</span>
                      {sessionState?.isStreaming && <span className="chat-session-running-dot" aria-hidden="true" />}
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </div>

      <div className="message-list" ref={messageListRef} onScroll={handleMessageListScroll}>
        {currentSessionState?.hasMore && (
          <div ref={sentinelRef} className="load-more-sentinel">
            {currentSessionState.isLoadingMore ? t('chat.loadingMore') : ''}
          </div>
        )}
        {error && (
          <article className="message-card system">
            <p>{error}</p>
          </article>
        )}
        {isLoading && (
          <article className="message-card system">
            <p>{t('chat.loadingMessages')}</p>          </article>
        )}
        {!isLoading && !error && currentSession && (
          <article className="message-card system session-header-card">
            <div className="session-header">
              <p>{sessionTitle}</p>
            </div>
          </article>
        )}
        {!isLoading && messages.length === 0 && !currentSession && (
          <article className="message-card system">
            <p>{t('chat.noMessages')}</p>
          </article>
        )}
        {messages.map((message, index) => {
          const previousMessage = index > 0 ? messages[index - 1] : null;
          const showRole = message.role === 'worker' && (!previousMessage || previousMessage.role !== 'worker');
          const roleLabel = message.senderName || t('chat.roleWorker');

          return (
            <article key={message.id} className={`message-card ${message.role}${!showRole ? ' continuation' : ''}`}>
              {showRole && <span className="message-role">{roleLabel}</span>}
              {message.role === 'worker' && message.reasoning && (
                <ReasoningPanel content={message.reasoning} defaultOpen={!!message.streaming} />
              )}
              {message.role === 'worker'
                ? (message.content && message.content !== '...' ? <div className="message-body"><MarkdownContent content={message.content} /></div> : null)
                : <div className="message-body">{message.content}</div>}
              {message.role === 'user' && message.runIndex !== undefined && (
                <div className="message-actions">
                  <button
                    type="button"
                    className="message-action-btn"
                    title={t('chat.cloneFromHere') || 'Clone session from here'}
                    onClick={() => void handleCloneSession(message.runIndex)}
                  >
                    <svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="1.5"><rect x="2" y="2" width="5" height="5" rx="0.5"/><rect x="9" y="9" width="5" height="5" rx="0.5"/><path d="M5 9V6h3"/></svg>
                  </button>
                </div>
              )}
              {message.role === 'worker' && message.toolCalls && message.toolCalls.length > 0 && (
                <ToolCallList
                  tools={message.toolCalls}
                  workspacePath={effectiveWorkspaces.length === 1 ? effectiveWorkspaces[0] : null}
                  onPreviewFile={handlePreviewFile}
                  messageId={message.id}
                />
              )}
              {message.role === 'worker' && (() => {
                // Last worker message in a consecutive group → show tokens
                const isLastInGroup = index === messages.length - 1 || messages[index + 1]?.role !== 'worker';
                if (!isLastInGroup) return null;

                // Live tokens during streaming (last message only)
                if (message.streaming && index === messages.length - 1) {
                  const live = currentSessionState?.liveTokenUsage;
                  if (live && (live.context > 0 || live.output > 0)) {
                    return (
                      <div className="message-metrics message-metrics-live">
                        <span className="metrics-live-dot" />
                        <span>{t('chat.tokenMetrics', { context: formatContextUsage(live.context, selectedModelContextWindow), output: live.output.toLocaleString() })}</span>
                      </div>
                    );
                  }
                  return null;
                }

                // Completed message: show context & output from this message
                // agno's input_tokens is cumulative — the last message has the largest value
                const lastContext = message.contextSize || 0;
                const lastOutput = message.outputTokens || 0;
                const totalInput = currentSessionState?.totalInputTokens || 0;
                const totalOutput = currentSessionState?.totalOutputTokens || 0;
                const hasCompaction = (currentSessionState?.compactedSegments ?? 0) > 0;
                if (lastContext > 0 || lastOutput > 0 || hasCompaction || totalInput > 0) {
                  return (
                    <div className="message-metrics">
                      <svg className="message-metrics-icon" viewBox="0 0 16 16" width="12" height="12"><path fill="currentColor" d="M3 12h2v-4H3v4zm4 0h2V6H7v6zm4 0h2V3h-2v9zM2 14h12V2H2v12z"/></svg>
                      <span>{t('chat.tokenMetrics', { context: formatContextUsage(lastContext, selectedModelContextWindow), output: lastOutput.toLocaleString() })}</span>
                      {totalInput > 0 && (
                        <button
                          type="button"
                          className="metrics-toggle-btn"
                          onClick={(e) => {
                            e.stopPropagation();
                            setShowTotalMetrics(!showTotalMetrics);
                          }}
                          title={t('chat.totalTokenMetrics', { input: totalInput.toLocaleString(), output: totalOutput.toLocaleString() })}
                        >
                          <svg viewBox="0 0 16 16" width="12" height="12"><path fill="currentColor" d="M8 0a8 8 0 100 16A8 8 0 008 0zm0 14.5a6.5 6.5 0 110-13 6.5 6.5 0 010 13zM8 3a5 5 0 100 10A5 5 0 008 3zm0 8.5a3.5 3.5 0 110-7 3.5 3.5 0 010 7z"/></svg>
                        </button>
                      )}
                      {hasCompaction && (
                        <button
                          type="button"
                          className="compaction-toggle-btn"
                          onClick={async (e) => {
                            e.stopPropagation();
                            if (showCompactionHistory) {
                              setShowCompactionHistory(false);
                              return;
                            }
                            try {
                              console.log('Fetching segments for session:', activeSessionId);
                              const segs = await getSessionSegments(activeSessionId!);
                              console.log('Segments received:', segs);
                              const compacted = segs.filter(s => s.status === 'compacted');
                              console.log('Compacted segments:', compacted);
                              setCompactionSegments(compacted);
                              setShowCompactionHistory(true);
                            } catch (err) {
                              console.error('Failed to fetch segments:', err);
                            }
                          }}
                          title={t('chat.compactedHint', { count: currentSessionState?.compactedSegments ?? 0 })}
                        >
                          📋
                        </button>
                      )}
                    </div>
                  );
                }
                return null;
              })()}
            </article>
          );
        })}
        {currentSessionState?.isCompacting && (
          <article className="message-card system">
            <div className="compaction-indicator">
              <span className="compaction-spinner" />
              <span>{t('chat.compacting') || 'Compressing context...'}</span>
            </div>
          </article>
        )}
      </div>

      {showCompactionHistory && compactionSegments.length > 0 && (
        <div className="member-overlay" style={{ zIndex: 100 }}>
          <div className="compaction-history-modal">
            <div className="compaction-history-header">
              <span>📋 {t('chat.compactedHint', { count: compactionSegments.length })}</span>
              <button
                type="button"
                className="compaction-close-btn"
                onClick={() => setShowCompactionHistory(false)}
              >
                ✕
              </button>
            </div>
            <div className="compaction-history-content">
              {compactionSegments.map((seg, i) => (
                <div key={seg.id} className="compaction-segment">
                  <div className="compaction-segment-header">
                    {t('chat.compactedSegment', { order: i + 1, runs: seg.run_count }) || `Compacted segment ${i + 1} (${seg.run_count} runs)`}
                  </div>
                  {seg.compaction_summary && (
                    <div className="compaction-segment-summary">
                      <MarkdownContent content={seg.compaction_summary} />
                    </div>
                  )}
                  {seg.compaction_meta && (
                    <div className="compaction-segment-meta">
                      {seg.compaction_meta.key_decisions && seg.compaction_meta.key_decisions.length > 0 && (
                        <div><strong>{t('chat.keyDecisions') || 'Key Decisions'}:</strong> {seg.compaction_meta.key_decisions.join(', ')}</div>
                      )}
                      {seg.compaction_meta.user_preferences && seg.compaction_meta.user_preferences.length > 0 && (
                        <div><strong>{t('chat.userPreferences') || 'User Preferences'}:</strong> {seg.compaction_meta.user_preferences.join(', ')}</div>
                      )}
                      {seg.compaction_meta.pending_tasks && seg.compaction_meta.pending_tasks.length > 0 && (
                        <div><strong>{t('chat.pendingTasks') || 'Pending Tasks'}:</strong> {seg.compaction_meta.pending_tasks.join(', ')}</div>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      <footer className="composer">
        <textarea
          placeholder={t('chat.placeholder')}
          rows={4}
          value={draft}
          onChange={(event) => {
            updateSessionState(worker.id, composerSessionId, (sessionState) => ({
              ...sessionState,
              draft: event.target.value,
            }));
          }}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.ctrlKey && !event.metaKey && !event.shiftKey) {
              event.preventDefault();
              void handleSend();
            }
          }}
        />

        {composerAttachments.length > 0 && (
          <div className="composer-attachments">
            {composerAttachments.map((attachment) => (
              <div key={attachment.id} className="composer-attachment-chip" title={attachment.path}>
                <span className="composer-attachment-kind">{getAttachmentKindLabel(attachment.kind, t)}</span>
                <span className="composer-attachment-name">{attachment.name}</span>
                <button type="button" className="composer-attachment-remove" onClick={() => removeAttachment(attachment.id)} disabled={isStreaming}>
                  ×
                </button>
              </div>
            ))}
          </div>
        )}

        <div className="composer-bottom">
          <div className="composer-left-meta">
            <div className="composer-tools">
              {workerWorkspaces.length > 0 && (
                <div className="composer-ws-dropdown-wrapper">
                  <button
                    type="button"
                    className="icon-button tooltip composer-ws-trigger"
                    aria-label="Workspaces"
                    title={effectiveWorkspaces.length === allWorkspacePaths.length ? 'All workspaces' : effectiveWorkspaces.map(wsLabel).join(', ')}
                    disabled={isStreaming}
                    onClick={() => setShowWsDropdown((v) => !v)}
                  >
                    <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M2 4h16M2 10h12M2 16h8"/><path d="M17 13l3 3-3 3" opacity="0.4"/></svg>
                    <span className="composer-ws-badge">
                      {effectiveWorkspaces.length === allWorkspacePaths.length
                        ? t('chat.allWorkspaces')
                        : effectiveWorkspaces.length === 1
                          ? wsLabel(effectiveWorkspaces[0])
                          : `${effectiveWorkspaces.length}/${allWorkspacePaths.length}`}
                    </span>
                  </button>
                  {showWsDropdown && (
                    <div className="composer-ws-dropdown">
                      {workerWorkspaces.map((ws) => {
                        const checked = effectiveWorkspaces.includes(ws.path);
                        return (
                          <label key={ws.path} className="composer-ws-option" title={ws.path}>
                            <input type="checkbox" checked={checked} onChange={() => handleWorkspaceToggle(ws.path, !checked)} disabled={isStreaming} />
                            <span>{wsLabel(ws.path)}</span>
                          </label>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}

              <button type="button" className="icon-button tooltip" aria-label={t('chat.attachmentFile')} title={t('chat.attachFile')} disabled={isStreaming || !workerCapabilities.file} onClick={() => void addAttachments('file')}>
                <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M4 4v12a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V8l-4-4H6a2 2 0 0 0-2 2z"/><polyline points="12 4 12 8 16 8"/></svg>
              </button>
              <button type="button" className="icon-button tooltip" aria-label={t('chat.attachmentImage')} title={workerCapabilities.image ? t('chat.attachImage') : t('chat.imageNotSupported')} disabled={isStreaming || !workerCapabilities.image} onClick={() => void addAttachments('image')}>
                <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="14" height="14" rx="2"/><circle cx="7.5" cy="7.5" r="1.5"/><polyline points="17 13 13 9 3 17"/></svg>
              </button>
              <button type="button" className="icon-button tooltip" aria-label={t('chat.attachmentVideo')} title={workerCapabilities.video ? t('chat.attachVideo') : t('chat.videoNotSupported')} disabled={isStreaming || !workerCapabilities.video} onClick={() => void addAttachments('video')}>
                <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="5" width="12" height="10" rx="2"/><polyline points="14 8 18 5.5 18 14.5 14 12"/></svg>
              </button>
              <button
                type="button"
                className={`icon-button tooltip${isListening ? ' voice-active' : ''}`}
                aria-label={t('chat.voice')}
                title={isListening ? t('chat.stopListening') : t('chat.voiceInput')}
                disabled={!speechSupported || isStreaming}
                onClick={toggleVoice}
              >
                <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><rect x="7" y="2" width="6" height="10" rx="3"/><path d="M4 10a6 6 0 0 0 12 0"/><line x1="10" y1="16" x2="10" y2="18"/></svg>
              </button>
            </div>
          </div>

          <div className="composer-actions">
            <div className="composer-model-picker" title={selectedModelLabel || selectedModelRef || t('chat.modelDefault')}>
              <select
                className="composer-model-select"
                value={selectedModelRef}
                onChange={(event) => handleModelChange(event.target.value)}
                disabled={isStreaming || !activeSessionId || providers.length === 0}
                aria-label={t('chat.modelSelect')}
              >
                {providers.length === 0 && defaultModelRef === '' ? (
                  <option value="">{t('chat.modelLoading') || 'Loading...'}</option>
                ) : (
                  <>
                    {!workerDefaultModelRef && defaultModelRef && (
                      <option value={defaultModelRef}>
                        {(() => {
                          for (const provider of providers) {
                            const model = provider.models.find((m) => m.id === defaultModelRef);
                            if (model) return model.name;
                          }
                          return defaultModelRef;
                        })()}
                      </option>
                    )}
                    {providers.map((provider) => (
                      <optgroup key={provider.id} label={provider.name}>
                        {provider.models.map((model) => (
                          <option key={model.id} value={model.id}>{model.name}</option>
                        ))}
                      </optgroup>
                    ))}
                  </>
                )}
              </select>
              {currentSession?.modelOverride && (
                <span className="composer-model-badge">override</span>
              )}
            </div>
            <button
              type="button"
              className={`composer-memory-toggle ${currentSession?.learningEnabled === false ? 'off' : 'on'}`}
              onClick={() => handleLearningToggle(currentSession?.learningEnabled === false)}
              disabled={isStreaming || !activeSessionId}
              title={currentSession?.learningEnabled === false ? t('chat.memoryOff') : t('chat.memoryOn')}
              aria-label={t('chat.memoryToggle')}
            >
              <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round">
                <path d="M10 2C7.24 2 5 4.24 5 7c0 1.34.53 2.55 1.39 3.45L10 16l3.61-5.55A4.97 4.97 0 0015 7c0-2.76-2.24-5-5-5z"/>
                <path d="M7.5 7a2.5 2.5 0 015 0"/>
                <line x1="10" y1="7" x2="10" y2="11"/>
              </svg>
              {currentSession?.learningEnabled === false && (
                <span className="composer-memory-badge">off</span>
              )}
            </button>
            {isStreaming ? (
              <button type="button" className="cancel-button" onClick={handleCancel}>
                {t('chat.cancel')}
              </button>
            ) : (
              <button type="button" className="primary-button" disabled={!draft.trim() && composerAttachments.length === 0} onClick={() => void handleSend()}>
                {t('chat.send')}
              </button>
            )}
          </div>
        </div>
      </footer>

      {showWorkerSettings && worker && (
        <WorkerSettingsSidebar
          worker={worker}
          onClose={() => setShowWorkerSettings(false)}
          onSaved={(updated) => {
            setShowWorkerSettings(false);
            // Refresh the worker list in parent if needed — for now just close
            void updated;
          }}
        />
      )}

      {showMemberSidebar && worker.type === 'Team' && (
        <MemberActivitySidebar
          memberActivitiesByRun={currentSessionState?.memberActivitiesByRun || []}
          onClose={() => setShowMemberSidebar(false)}
        />
      )}

      <FilePreviewSidebar
        open={showFilePreviewSidebar}
        onToggle={() => setShowFilePreviewSidebar(v => !v)}
        workspaces={workspaceInfos}
        externalPreviewFile={!previewFileHandled ? pendingPreviewFile : null}
        onExternalPreviewHandled={handlePreviewFileHandled}
      />

      {currentSessionState?.pendingApproval && (
        <ToolApprovalDialog
          approval={currentSessionState.pendingApproval}
          onApprove={(alwaysAllowDir?: string) => void handleApproval(true, alwaysAllowDir)}
          onReject={() => void handleApproval(false)}
        />
      )}

      {showTotalMetrics && (currentSessionState?.totalInputTokens ?? 0) > 0 && (
        <div className="member-overlay" style={{ zIndex: 100 }} onClick={(e) => { if (e.target === e.currentTarget) setShowTotalMetrics(false); }}>
          <div className="total-metrics-popup">
            <div className="total-metrics-header">
              <span>{t('chat.totalTokenMetricsTitle') || '累计 Token 统计'}</span>
              <button type="button" className="compaction-close-btn" onClick={() => setShowTotalMetrics(false)}>✕</button>
            </div>
            <div className="total-metrics-content">
              <div className="total-metrics-row">
                <span className="total-metrics-label">{t('chat.totalInput') || '输入'}:</span>
                <span className="total-metrics-value">{(currentSessionState?.totalInputTokens ?? 0).toLocaleString()}</span>
              </div>
              <div className="total-metrics-row">
                <span className="total-metrics-label">{t('chat.totalOutput') || '输出'}:</span>
                <span className="total-metrics-value">{(currentSessionState?.totalOutputTokens ?? 0).toLocaleString()}</span>
              </div>
              <div className="total-metrics-row total-metrics-total">
                <span className="total-metrics-label">{t('chat.totalSum') || '总计'}:</span>
                <span className="total-metrics-value">{((currentSessionState?.totalInputTokens ?? 0) + (currentSessionState?.totalOutputTokens ?? 0)).toLocaleString()}</span>
              </div>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

function MemberActivitySidebar({ memberActivitiesByRun, onClose }: { memberActivitiesByRun: MemberActivitiesByRun[]; onClose: () => void }) {
  const { t } = useI18n();
  const [openMembers, setOpenMembers] = useState<Set<string>>(new Set());
  const [openTools, setOpenTools] = useState<Set<string>>(new Set());

  const allActivities = memberActivitiesByRun.flatMap(r => r.activities);
  const completed = allActivities.filter(a => a.status === 'completed').length;
  const total = allActivities.length;

  const toggle = (set: Set<string>, key: string) => {
    const next = new Set(set);
    if (next.has(key)) next.delete(key); else next.add(key);
    return next;
  };

  return (
    <div className="member-overlay" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <aside className="member-sidebar">
        <div className="member-sidebar-header">
          <div className="member-sidebar-title">
            <svg viewBox="0 0 20 20" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><circle cx="7" cy="7" r="3"/><path d="M1 17v-1a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v1"/><circle cx="15" cy="7" r="2.5"/><path d="M15 11.5a3 3 0 0 1 3 3v.5"/></svg>
            <h3>{t('chat.memberActivities', { count: total, completed })}</h3>
          </div>
          <button type="button" className="icon-button member-sidebar-close" onClick={onClose} aria-label="Close">
            <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><line x1="5" y1="5" x2="15" y2="15" /><line x1="15" y1="5" x2="5" y2="15" /></svg>
          </button>
        </div>
        <div className="member-sidebar-body">
          {memberActivitiesByRun.length === 0 && (
            <div className="member-sidebar-empty">{t('chat.noMemberActivities')}</div>
          )}
          {memberActivitiesByRun.map((run, ri) => {
            // Count occurrences of each agentName for disambiguation
            const nameCount: Record<string, number> = {};
            return (
            <div key={run.runId || ri} className="member-run-group">
              {run.activities.map((activity, ai) => {
                const baseName = activity.agentName || activity.agentId;
                const seq = (nameCount[baseName] = (nameCount[baseName] || 0) + 1);
                const displayName = seq > 1 ? `${baseName} #${seq}` : baseName;
                const memberKey = `${run.runId}-${ai}`;
                const isMemberOpen = openMembers.has(memberKey);
                const toolsKey = `${memberKey}-tools`;
                const isToolsOpen = openTools.has(toolsKey);
                return (
                  <div key={memberKey} className="member-activity-item">
                    <button type="button" className="member-activity-item-header" onClick={() => setOpenMembers(prev => toggle(prev, memberKey))}>
                      <span>{activity.status === 'completed' ? '✅' : activity.status === 'error' ? '❌' : '⏳'}</span>
                      <span className="member-activity-agent">{displayName}</span>
                      {activity.toolCalls.length > 0 && <span className="member-activity-tool-count">{activity.toolCalls.length} tools</span>}
                      <span className="member-activity-toggle">{isMemberOpen ? '▾' : '▸'}</span>
                    </button>
                    {isMemberOpen && (
                      <>
                        {activity.toolCalls.length > 0 && (
                          <div className="member-section">
                            <button type="button" className="member-section-header" onClick={() => setOpenTools(prev => toggle(prev, toolsKey))}>
                              <span className="member-section-toggle">{isToolsOpen ? '▾' : '▸'}</span>
                              <span>{t('tool.title')} ({activity.toolCalls.length})</span>
                            </button>
                            {isToolsOpen && (
                              <div className="member-activity-tools">
                                <ToolCallList tools={activity.toolCalls} />
                              </div>
                            )}
                          </div>
                        )}
                        {activity.content && (
                          <div className="member-activity-content-full"><MarkdownContent content={activity.content} /></div>
                        )}
                      </>
                    )}
                  </div>
                );
              })}
            </div>
            );
          })}
        </div>
      </aside>
    </div>
  );
}

function ToolApprovalDialog({ approval, onApprove, onReject }: {
  approval: { runId: string; approvals: ToolApprovalItem[] };
  onApprove: (alwaysAllowDir?: string) => void;
  onReject: () => void;
}) {
  const [alwaysAllow, setAlwaysAllow] = useState(false);

  // Extract the directory from the first approval item's file_path
  const firstFilePath = approval.approvals[0]?.toolArgs?.file_path as string || approval.approvals[0]?.toolArgs?.path as string || '';
  const parentDir = firstFilePath ? firstFilePath.replace(/[/\\][^/\\]+$/, '') : '';

  return (
    <div className="member-overlay approval-overlay" style={{ zIndex: 100 }}>
      <div className="approval-dialog" style={{
        background: '#fff',
        border: '1px solid rgba(132, 146, 170, 0.25)',
        borderRadius: '12px',
        padding: '24px',
        maxWidth: '480px',
        width: '90%',
        margin: 'auto',
        boxShadow: '0 8px 32px rgba(0,0,0,0.12)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '16px' }}>
          <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="#f59e0b" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
            <line x1="12" y1="9" x2="12" y2="13" />
            <line x1="12" y1="17" x2="12.01" y2="17" />
          </svg>
          <h3 style={{ margin: 0, fontSize: '16px', fontWeight: 600, color: '#1e293b' }}>Write Approval Required</h3>
        </div>

        <div style={{ marginBottom: '16px' }}>
          {approval.approvals.map((item, i) => (
            <div key={item.toolCallId || i} style={{
              padding: '10px 12px',
              background: '#f0f3f9',
              borderRadius: '8px',
              marginBottom: i < approval.approvals.length - 1 ? '8px' : 0,
              fontSize: '13px',
            }}>
              <div style={{ fontWeight: 500, color: '#1e293b', wordBreak: 'break-all' }}>
                {item.description || `${item.toolName}`}
              </div>
            </div>
          ))}
        </div>

        {parentDir && (
          <label style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            marginBottom: '16px',
            fontSize: '13px',
            color: '#64748b',
            cursor: 'pointer',
          }}>
            <input
              type="checkbox"
              checked={alwaysAllow}
              onChange={(e) => setAlwaysAllow(e.target.checked)}
            />
            Always allow writes to <code style={{ fontSize: '12px', wordBreak: 'break-all', color: '#31415d' }}>{parentDir}</code>
          </label>
        )}

        <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
          <button
            type="button"
            onClick={() => onReject()}
            style={{
              padding: '8px 16px',
              borderRadius: '8px',
              border: '1px solid rgba(132, 146, 170, 0.25)',
              background: 'transparent',
              color: '#31415d',
              cursor: 'pointer',
              fontSize: '13px',
            }}
          >
            Reject
          </button>
          <button
            type="button"
            onClick={() => onApprove(alwaysAllow ? parentDir : undefined)}
            style={{
              padding: '8px 16px',
              borderRadius: '8px',
              border: 'none',
              background: '#4f46e5',
              color: 'white',
              cursor: 'pointer',
              fontSize: '13px',
              fontWeight: 500,
            }}
          >
            Approve
          </button>
        </div>
      </div>
    </div>
  );
}
