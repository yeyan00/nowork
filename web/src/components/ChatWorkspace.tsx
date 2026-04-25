import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useI18n } from '../i18n';
import { cancelRun, createSession, listMessages, listSessions, sendMessageStream, updateSession } from '../lib/backend';
import type { AgentEvent } from '../lib/backend';
import type { ChatAttachment, ChatMessage, ToolCall, WorkerSummary, WorkspaceBinding } from '../types';
import type { CachedSessionState, CachedWorkerState } from './chatState';
import { createEmptyWorkerState, ensureSessionState, getVisibleAndOverflowSessionIds } from './chatState';
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
    isLoading: false,
    isLoadingMore: false,
    hasMore: false,
    isStreaming: false,
    runId: null,
    error: null,
    loaded: false,
    lastActiveAt: 0,
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
  const [showWsDropdown, setShowWsDropdown] = useState(false);
  const [pendingSessionWorkspaces, setPendingSessionWorkspaces] = useState<Record<string, string>>({});
  const [draftAttachments, setDraftAttachments] = useState<Record<string, ChatAttachment[]>>({});
  const [isListening, setIsListening] = useState(false);
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
  const composerSessionId = activeSessionId ?? DRAFT_SESSION_ID;
  const composerSessionState = currentWorkerState
    ? currentWorkerState.sessionStates[composerSessionId] ?? createSessionState(composerSessionId)
    : createSessionState(DRAFT_SESSION_ID);
  const currentSession = currentWorkerState?.sessions.find((session) => session.id === activeSessionId) ?? null;
  const workerWorkspaces = useMemo(() => getWorkerWorkspaces(worker), [worker]);

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

  useEffect(() => {
    if (!worker || !requestedSessionId || !currentWorkerState?.sessionsLoaded) return;
    const hasSession = currentWorkerState.sessions.some((session) => session.id === requestedSessionId);
    if (!hasSession) return;
    if (currentWorkerState.activeSessionId !== requestedSessionId) {
      activateSession(worker.id, requestedSessionId);
    }
    onRequestedSessionHandled?.();
  }, [activateSession, currentWorkerState?.activeSessionId, currentWorkerState?.sessions, currentWorkerState?.sessionsLoaded, onRequestedSessionHandled, requestedSessionId, worker]);

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

    const now = new Date().toISOString();
    const ws = effectiveWorkspaces.length > 0 && effectiveWorkspaces.length < allWorkspacePaths.length
      ? effectiveWorkspaces
      : null;
    const nextSession = await createSession(worker.id, now, ws);
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
        const now = new Date().toISOString();
        const ws = effectiveWorkspaces.length > 0 && effectiveWorkspaces.length < allWorkspacePaths.length
          ? effectiveWorkspaces
          : null;
        const createdSession = await createSession(targetWorkerId, now, ws);
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
        // For Team workers, only listen to TeamModelRequestCompleted (orchestrator),
        // ignoring member-agent ModelRequestCompleted events.
        if (eventType === contextEventName) {
          const m = event.metrics;
          if (m) {
            liveInput = m.input_tokens ?? 0;
            liveOutput = m.output_tokens ?? 0;
            updateSessionState(targetWorkerId, sessionId!, (sessionState) => ({
              ...sessionState,
              liveTokenUsage: { context: liveInput, output: liveOutput },
            }));
          }
          return;
        }
        // Ignore member-agent ModelRequestCompleted when inside a Team worker
        if (isTeamWorker && eventType === 'ModelRequestCompleted') {
          return;
        }

        if (eventType === 'ToolCallStarted' || eventType === 'ToolCallCompleted' || eventType === 'ToolCallError') {
          if (event.toolCalls) {
            accumulatedTools = event.toolCalls;
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
          if (event.toolCalls) accumulatedTools = event.toolCalls;

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

  if (!worker) {
    return <section className="chat-workspace">{t('chat.selectWorker')}</section>;
  }

  const messages = currentSessionState?.messages ?? [];
  const isLoading = !currentWorkerState?.sessionsLoaded || currentSessionState?.isLoading === true;
  const isStreaming = currentSessionState?.isStreaming === true;
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
            >
              <span>{formatSessionTime(session.updatedAt || session.createdAt, t('chat.newSessionTitle'))}</span>
              {sessionState?.isStreaming && <span className="chat-session-running-dot" aria-hidden="true" />}
            </button>
          );
        })}
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
                      <span>{formatSessionTime(session.updatedAt || session.createdAt, t('chat.newSessionTitle'))}</span>
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
          <article className="message-card system">
            <p>{sessionTitle}</p>
          </article>
        )}
        {!isLoading && messages.length === 0 && !currentSession && (
          <article className="message-card system">
            <p>{t('chat.noMessages')}</p>
          </article>
        )}
        {messages.map((message, index) => {
          const previousMessage = index > 0 ? messages[index - 1] : null;
          const showRole = message.role !== 'worker' || !previousMessage || previousMessage.role !== 'worker';
          const roleLabel = message.role === 'worker' ? (message.senderName || t('chat.roleWorker')) : message.role === 'user' ? t('chat.roleUser') : t('chat.roleSystem');

          return (
            <article key={message.id} className={`message-card ${message.role}${!showRole ? ' continuation' : ''}`}>
              {showRole && <span className="message-role">{roleLabel}</span>}
              {message.role === 'worker' && message.reasoning && (
                <ReasoningPanel content={message.reasoning} defaultOpen={!!message.streaming} />
              )}
              {message.role === 'worker' && message.toolCalls && message.toolCalls.length > 0 && (
                <ToolCallList tools={message.toolCalls} />
              )}
              {message.role === 'worker'
                ? <div className="message-body"><MarkdownContent content={message.content} /></div>
                : <div className="message-body">{message.content}</div>}
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
                        <span>{t('chat.tokenMetrics', { context: live.context.toLocaleString(), output: live.output.toLocaleString() })}</span>
                      </div>
                    );
                  }
                  return null;
                }

                // Completed message: show last context & output from this group
                let lastContext = 0;
                let lastOutput = 0;
                for (let i = index; i >= 0; i--) {
                  if (messages[i].role !== 'worker') break;
                  if (messages[i].contextSize) lastContext = messages[i].contextSize!;
                  if (messages[i].outputTokens) lastOutput = messages[i].outputTokens!;
                }
                if (lastContext > 0 || lastOutput > 0) {
                  return (
                    <div className="message-metrics">
                      <svg className="message-metrics-icon" viewBox="0 0 16 16" width="12" height="12"><path fill="currentColor" d="M3 12h2v-4H3v4zm4 0h2V6H7v6zm4 0h2V3h-2v9zM2 14h12V2H2v12z"/></svg>
                      <span>{t('chat.tokenMetrics', { context: lastContext.toLocaleString(), output: lastOutput.toLocaleString() })}</span>
                    </div>
                  );
                }
                return null;
              })()}
            </article>
          );
        })}
      </div>

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
    </section>
  );
}
