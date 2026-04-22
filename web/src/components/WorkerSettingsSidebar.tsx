/**
 * WorkerSettingsSidebar — floating sidebar shell that hosts WorkerSettingsPanel.
 * Positioned relative to .chat-workspace, slides in from the right.
 */

import type { WorkerSummary } from '../types';
import { WorkerSettingsPanel } from './WorkerSettingsPanel';

interface WorkerSettingsSidebarProps {
  worker: WorkerSummary;
  onClose: () => void;
  onSaved?: (worker: WorkerSummary) => void;
}

export function WorkerSettingsSidebar({ worker, onClose, onSaved }: WorkerSettingsSidebarProps) {
  return (
    <div className="ws-sidebar-overlay" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <aside className="ws-sidebar">
        <div className="ws-sidebar-header">
          <div>
            <h3>{worker.name}</h3>
            <span className={`worker-badge ${worker.type.toLowerCase()}`}>{worker.type}</span>
          </div>
          <button type="button" className="icon-button ws-sidebar-close" onClick={onClose} aria-label="Close">
            <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><line x1="5" y1="5" x2="15" y2="15" /><line x1="15" y1="5" x2="5" y2="15" /></svg>
          </button>
        </div>
        <WorkerSettingsPanel worker={worker} onSave={(saved) => onSaved?.(saved)} navLayout="horizontal" />
      </aside>
    </div>
  );
}
