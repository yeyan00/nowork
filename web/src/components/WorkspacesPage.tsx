import { useMemo, useState } from 'react';
import { useI18n } from '../i18n';
import type { WorkspaceSummary } from '../types';

interface WorkspacesPageProps {
  workspaces: WorkspaceSummary[];
  activeWorkspaceId: string | null;
  onOpenWorkspace: (workspaceId: string) => void;
}

function formatPermission(permission: WorkspaceSummary['permission'], t: (key: string) => string): string {
  return permission === 'read' ? t('workspace.readOnly') : t('workspace.readWrite');
}

export function WorkspacesPage({ workspaces, activeWorkspaceId, onOpenWorkspace }: WorkspacesPageProps) {
  const { t } = useI18n();
  const [query, setQuery] = useState('');

  const filteredWorkspaces = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    if (!keyword) return workspaces;
    return workspaces.filter((workspace) => [workspace.name, workspace.path]
      .join(' ')
      .toLowerCase()
      .includes(keyword));
  }, [query, workspaces]);

  return (
    <section className="page-frame workspaces-page">
      <header className="page-header">
        <div>
          <h1>{t('workspace.title')}</h1>
          <p>{t('workspace.subtitle')}</p>
        </div>
      </header>

      <div className="workspace-toolbar">
        <input
          type="text"
          className="settings-input workspace-search-input"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={t('workspace.search')}
        />
      </div>

      <div className="workspace-card-grid">
        {filteredWorkspaces.map((workspace) => (
          <button
            key={workspace.id}
            type="button"
            className={workspace.id === activeWorkspaceId ? 'workspace-card active' : 'workspace-card'}
            onClick={() => onOpenWorkspace(workspace.id)}
          >
            <div className="workspace-card-topline">
              <span className="workspace-card-icon">W</span>
              <span className="workspace-permission-badge">{formatPermission(workspace.permission, t)}</span>
            </div>
            <strong>{workspace.name}</strong>
            <span className="workspace-card-path" title={workspace.path}>{workspace.path}</span>
            <span className="workspace-card-meta">{t('workspace.workerCount', { count: workspace.workerIds.length })}</span>
          </button>
        ))}
        {filteredWorkspaces.length === 0 && (
          <div className="workspace-empty-state">{t('workspace.empty')}</div>
        )}
      </div>
    </section>
  );
}
