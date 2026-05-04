import { useCallback, useMemo, useState } from 'react';
import { useI18n } from '../i18n';
import type { WorkspaceInfo } from '../types';

interface WorkspaceSelectorProps {
  workspaces: WorkspaceInfo[];
  currentPath: string | null;
  onSwitch: (path: string) => void;
}

/**
 * Dropdown to select the active workspace for file browsing.
 * Workspaces come from the worker's `workspaces` config.
 */
export function WorkspaceSelector({ workspaces, currentPath, onSwitch }: WorkspaceSelectorProps) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);

  const current = useMemo(
    () => workspaces.find(ws => ws.path === currentPath),
    [workspaces, currentPath],
  );

  const handleSelect = useCallback((path: string) => {
    onSwitch(path);
    setOpen(false);
  }, [onSwitch]);

  if (workspaces.length === 0) {
    return (
      <div className="workspace-selector workspace-selector-empty">
        <span className="workspace-selector-label">
          {t('filePreview.noWorkspaces') || 'No workspaces'}
        </span>
      </div>
    );
  }

  // Single workspace: just show name, no dropdown needed
  if (workspaces.length === 1) {
    const ws = workspaces[0];
    return (
      <div className="workspace-selector workspace-selector-single" title={ws.path}>
        <span className="workspace-selector-icon">📁</span>
        <span className="workspace-selector-label">{ws.name}</span>
        {ws.permission === 'read' && <span className="workspace-read-badge">RO</span>}
      </div>
    );
  }

  return (
    <div className="workspace-selector">
      <button
        type="button"
        className="workspace-selector-trigger"
        onClick={() => setOpen(v => !v)}
        title={current?.path || ''}
      >
        <span className="workspace-selector-icon">📁</span>
        <span className="workspace-selector-label">{current?.name || (t('filePreview.selectWorkspace') || 'Select workspace')}</span>
        <span className="workspace-selector-arrow">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="workspace-selector-dropdown">
          {workspaces.map(ws => (
            <button
              key={ws.path}
              type="button"
              className={`workspace-selector-item ${ws.path === currentPath ? 'active' : ''}`}
              onClick={() => handleSelect(ws.path)}
              title={ws.path}
            >
              <span className="workspace-selector-icon">📁</span>
              <span className="workspace-selector-item-name">{ws.name}</span>
              {ws.permission === 'read' && <span className="workspace-read-badge">RO</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
