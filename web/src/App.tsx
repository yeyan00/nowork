import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { BackendStatus } from './components/BackendStatus';
import { ChatWorkspace } from './components/ChatWorkspace';
import { ChannelsPage } from './components/ChannelsPage';
import { ExtensionsPage } from './components/ExtensionsPage';
import { HelpPanel } from './components/HelpPanel';
import { KnowledgePage } from './components/KnowledgePage';
import { ManagementPage } from './components/ManagementPage';
import { MCPPage } from './components/MCPPage';
import { ModelsPage } from './components/ModelsPage';
import { NavRail } from './components/NavRail';
import { SkillsPage } from './components/SkillsPage';
import { SchedulesPage } from './components/SchedulesPage';
import { SettingsPage } from './components/SettingsPage';
import { WorkerList } from './components/WorkerList';
import { WorkersManager } from './components/WorkersManager';
import { WorkspacesPage } from './components/WorkspacesPage';
import { getRunningWorkerIds } from './components/chatState';
import { managementCards } from './data/mockData';
import { listWorkers, listWorkspaces } from './lib/backend';
import type { AppPage, WorkerSummary, WorkspaceSummary } from './types';
import type { CachedWorkerState } from './components/chatState';

function parseRecentTime(value?: string | null): number {
  if (!value) return 0;
  const numeric = Number(value);
  if (!Number.isNaN(numeric) && numeric > 0) {
    return numeric > 1e12 ? numeric : numeric * 1000;
  }
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? 0 : parsed;
}

function getCachedWorkerRecentTime(workerState?: CachedWorkerState | null): number {
  if (!workerState) return 0;
  return Object.values(workerState.sessionStates).reduce(
    (latest, sessionState) => Math.max(latest, sessionState.lastActiveAt || 0),
    0,
  );
}

export default function App() {
  const [activePage, setActivePage] = useState<AppPage>('Chat');
  const [workers, setWorkers] = useState<WorkerSummary[]>([]);
  const [workspaces, setWorkspaces] = useState<WorkspaceSummary[]>([]);
  const [activeWorkspaceId, setActiveWorkspaceId] = useState<string | null>(null);
  const [activeWorkerId, setActiveWorkerId] = useState<string | null>(null);
  const [chatStates, setChatStates] = useState<Record<string, CachedWorkerState>>({});
  const [requestedSessionId, setRequestedSessionId] = useState<string | null>(null);
  const [showHelp, setShowHelp] = useState(false);

  const [sidebarWidth, setSidebarWidth] = useState(280);
  const dragging = useRef(false);
  const startX = useRef(0);
  const startWidth = useRef(0);

  useEffect(() => {
    let cancelled = false;
    let retries = 0;

    async function loadInitialData() {
      while (retries < 60 && !cancelled) {
        try {
          const [nextWorkers, nextWorkspaces] = await Promise.all([listWorkers(), listWorkspaces()]);
          if (!cancelled) {
            setWorkers(nextWorkers);
            setWorkspaces(nextWorkspaces);
            const firstWorkspace = nextWorkspaces[0] ?? null;
            setActiveWorkspaceId(firstWorkspace?.id ?? null);
            const firstWorkspaceWorkerId = firstWorkspace?.workerIds.find((workerId) => nextWorkers.some((worker) => worker.id === workerId));
            setActiveWorkerId(firstWorkspaceWorkerId ?? nextWorkers[0]?.id ?? null);
          }
          return;
        } catch {
          retries++;
          await new Promise((r) => setTimeout(r, 1000));
        }
      }
      // Give up after 30s
      if (!cancelled) {
        setWorkers([]);
        setWorkspaces([]);
        setActiveWorkspaceId(null);
        setActiveWorkerId(null);
      }
    }

    void loadInitialData();

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (activePage === 'Chat') {
      void Promise.all([listWorkers(), listWorkspaces()]).then(([nextWorkers, nextWorkspaces]) => {
        setWorkers(nextWorkers);
        setWorkspaces(nextWorkspaces);
        const nextWorkspace = nextWorkspaces.find((workspace) => workspace.id === activeWorkspaceId) ?? nextWorkspaces[0] ?? null;
        if (nextWorkspace?.id !== activeWorkspaceId) {
          setActiveWorkspaceId(nextWorkspace?.id ?? null);
        }
        const availableWorkerIds = nextWorkspace?.workerIds ?? nextWorkers.map((worker) => worker.id);
        if (!activeWorkerId || !availableWorkerIds.includes(activeWorkerId)) {
          const fallbackWorkerId = availableWorkerIds.find((workerId) => nextWorkers.some((worker) => worker.id === workerId));
          setActiveWorkerId(fallbackWorkerId ?? nextWorkers[0]?.id ?? null);
        }
      }).catch(() => {});
    }
  }, [activePage]);

  const handleDividerDown = useCallback((e: React.PointerEvent) => {
    dragging.current = true;
    startX.current = e.clientX;
    startWidth.current = sidebarWidth;
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
  }, [sidebarWidth]);

  const handleDividerMove = useCallback((e: React.PointerEvent) => {
    if (!dragging.current) return;
    const delta = e.clientX - startX.current;
    const next = Math.min(480, Math.max(180, startWidth.current + delta));
    setSidebarWidth(next);
  }, []);

  const handleDividerUp = useCallback(() => {
    dragging.current = false;
  }, []);

  const sortedWorkers = useMemo(() => {
    return [...workers].sort((left, right) => {
      const rightRecent = Math.max(parseRecentTime(right.recent), getCachedWorkerRecentTime(chatStates[right.id]));
      const leftRecent = Math.max(parseRecentTime(left.recent), getCachedWorkerRecentTime(chatStates[left.id]));
      if (rightRecent !== leftRecent) {
        return rightRecent - leftRecent;
      }
      return left.name.localeCompare(right.name);
    });
  }, [chatStates, workers]);

  const activeWorkspace = workspaces.find((workspace) => workspace.id === activeWorkspaceId) ?? null;
  const workspaceWorkers = useMemo(() => {
    if (!activeWorkspace) return sortedWorkers;
    return sortedWorkers.filter((worker) => activeWorkspace.workerIds.includes(worker.id));
  }, [activeWorkspace, sortedWorkers]);
  const activeWorker = workspaceWorkers.find((worker) => worker.id === activeWorkerId) ?? workspaceWorkers[0] ?? null;
  const runningWorkerIds = useMemo(() => getRunningWorkerIds(chatStates), [chatStates]);

  const openChatSession = useCallback((workerId: string, sessionId?: string | null) => {
    setActiveWorkerId(workerId);
    setActivePage('Chat');
    setRequestedSessionId(sessionId ?? null);
  }, []);

  const openWorkspace = useCallback((workspaceId: string) => {
    const workspace = workspaces.find((item) => item.id === workspaceId) ?? null;
    setActiveWorkspaceId(workspaceId);
    if (workspace && (!activeWorkerId || !workspace.workerIds.includes(activeWorkerId))) {
      const fallbackWorkerId = workspace.workerIds.find((workerId) => workers.some((worker) => worker.id === workerId));
      setActiveWorkerId(fallbackWorkerId ?? null);
    }
    setActivePage('Chat');
  }, [activeWorkerId, workers, workspaces]);

  let content;

  if (activePage === 'Chat') {
    content = (
      <div className="chat-layout">
        <div className="chat-sidebar" style={{ width: sidebarWidth }}>
          <WorkerList
            workers={workspaceWorkers}
            activeWorkerId={activeWorker?.id ?? undefined}
            runningWorkerIds={runningWorkerIds}
            onSelect={setActiveWorkerId}
            title={activeWorkspace?.name ?? undefined}
            subtitle={activeWorkspace?.path ?? undefined}
          />
        </div>
        <div
          className="chat-divider"
          onPointerDown={handleDividerDown}
          onPointerMove={handleDividerMove}
          onPointerUp={handleDividerUp}
        />
        <div className="chat-main">
          <ChatWorkspace
            worker={activeWorker}
            workspace={activeWorkspace}
            chatStates={chatStates}
            onChatStatesChange={setChatStates}
            requestedSessionId={requestedSessionId}
            onRequestedSessionHandled={() => setRequestedSessionId(null)}
          />
        </div>
      </div>
    );
  } else if (activePage === 'Workspaces') {
    content = <WorkspacesPage workspaces={workspaces} activeWorkspaceId={activeWorkspaceId} onOpenWorkspace={openWorkspace} />;
  } else if (activePage === 'Workers') {
    content = <WorkersManager onWorkerUpdate={(updated) => {
      setWorkers((current) => current.map((w) => w.id === updated.id ? updated : w));
    }} />;
  } else if (activePage === 'Channels') {
    content = <ChannelsPage />;
  } else if (activePage === 'Schedules') {
    content = <SchedulesPage onOpenChatSession={openChatSession} />;
  } else if (activePage === 'Skills') {
    content = <SkillsPage />;
  } else if (activePage === 'Models') {
    content = <ModelsPage />;
  } else if (activePage === 'MCP') {
    content = <MCPPage />;
  } else if (activePage === 'Knowledge') {
    content = <KnowledgePage />;
  } else if (activePage === 'Settings') {
    content = <SettingsPage />;
  } else if (activePage === 'Extensions') {
    content = <ExtensionsPage />;
  } else {
    content = (
      <ManagementPage
        title={activePage as string}
        subtitle={`Prototype frame for ${(activePage as string).toLowerCase()} management.`}
        cards={managementCards[activePage as string]}
      />
    );
  }

  return (
    <div className="app-desktop">
      <div className="app-window">
        <NavRail activePage={activePage} onChange={setActivePage} onHelp={() => setShowHelp(true)} />
        <main className="app-content">
          <div className="app-status-bar">
            <BackendStatus />
          </div>
          {content}
          {showHelp && <HelpPanel onClose={() => setShowHelp(false)} />}
        </main>
      </div>
    </div>
  );
}
