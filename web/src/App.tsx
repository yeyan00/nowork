import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { BackendStatus } from './components/BackendStatus';
import { ChatWorkspace } from './components/ChatWorkspace';
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
import { getRunningWorkerIds } from './components/chatState';
import { managementCards } from './data/mockData';
import { listWorkers } from './lib/backend';
import type { AppPage, WorkerSummary } from './types';
import type { CachedWorkerState } from './components/chatState';

export default function App() {
  const [activePage, setActivePage] = useState<AppPage>('Chat');
  const [workers, setWorkers] = useState<WorkerSummary[]>([]);
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

    async function loadWorkers() {
      while (retries < 30 && !cancelled) {
        try {
          const nextWorkers = await listWorkers();
          if (!cancelled) {
            setWorkers(nextWorkers);
            if (activePage === 'Chat') {
              setActiveWorkerId(nextWorkers[0]?.id ?? null);
            }
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
        setActiveWorkerId(null);
      }
    }

    void loadWorkers();

    return () => {
      cancelled = true;
    };
  }, []);

  // Re-fetch workers when switching back to Chat page
  useEffect(() => {
    if (activePage === 'Chat') {
      void listWorkers().then((w) => {
        setWorkers(w);
        if (w.length > 0 && !w.find((ww) => ww.id === activeWorkerId)) {
          setActiveWorkerId(w[0].id);
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

  const activeWorker = workers.find((worker) => worker.id === activeWorkerId) ?? null;
  const runningWorkerIds = useMemo(() => getRunningWorkerIds(chatStates), [chatStates]);

  const openChatSession = useCallback((workerId: string, sessionId?: string | null) => {
    setActiveWorkerId(workerId);
    setActivePage('Chat');
    setRequestedSessionId(sessionId ?? null);
  }, []);

  let content;

  if (activePage === 'Chat') {
    content = (
      <div className="chat-layout">
        <div className="chat-sidebar" style={{ width: sidebarWidth }}>
          <WorkerList
            workers={workers}
            activeWorkerId={activeWorkerId ?? undefined}
            runningWorkerIds={runningWorkerIds}
            onSelect={setActiveWorkerId}
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
            chatStates={chatStates}
            onChatStatesChange={setChatStates}
            requestedSessionId={requestedSessionId}
            onRequestedSessionHandled={() => setRequestedSessionId(null)}
          />
        </div>
      </div>
    );
  } else if (activePage === 'Workers') {
    content = <WorkersManager onWorkerUpdate={(updated) => {
      setWorkers((current) => current.map((w) => w.id === updated.id ? updated : w));
    }} />;
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
