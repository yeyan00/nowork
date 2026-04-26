/**
 * WorkersManager — worker studio page.
 * Uses the shared WorkerSettingsPanel for the settings area.
 */

import { useCallback, useEffect, useState } from 'react';
import { useI18n } from '../i18n';
import {
  createWorker,
  listWorkers,
} from '../lib/backend';
import type { WorkerSummary } from '../types';
import { WorkerSettingsPanel } from './WorkerSettingsPanel';

type WorkerTab = 'Agents' | 'Teams';

const workerTypeMap: Record<WorkerTab, WorkerSummary['type']> = {
  Agents: 'Agent',
  Teams: 'Team',
};

const tabI18nKeys: Record<WorkerTab, string> = {
  Agents: 'workers.agents',
  Teams: 'workers.teams',
};

interface WorkersManagerProps {
  onWorkerUpdate?: (worker: WorkerSummary) => void;
}

export function WorkersManager({ onWorkerUpdate }: WorkersManagerProps) {
  const { t } = useI18n();
  const [tab, setTab] = useState<WorkerTab>('Agents');
  const [workers, setWorkers] = useState<WorkerSummary[]>([]);
  const [selectedWorkerId, setSelectedWorkerId] = useState<string | null>(null);
  const [allAgents, setAllAgents] = useState<WorkerSummary[]>([]);

  // Create dialog state
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState('');
  const [cloneFromId, setCloneFromId] = useState<string>('');
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState('');

  const reloadWorkers = useCallback((selectId?: string) => {
    void listWorkers(workerTypeMap[tab]).then((w) => {
      setWorkers(w);
      setSelectedWorkerId(selectId ?? (w.length > 0 ? w[0].id : null));
    });
  }, [tab]);

  useEffect(() => {
    reloadWorkers();
  }, [reloadWorkers]);

  useEffect(() => {
    void listWorkers('Agent').then(setAllAgents).catch(() => {});
  }, []);

  const selectedWorker = workers.find((item) => item.id === selectedWorkerId) ?? null;

  const handleCreate = useCallback(async () => {
    const name = newName.trim();
    if (!name) return;
    setCreating(true);
    setCreateError('');
    try {
      const created = await createWorker({
        type: workerTypeMap[tab],
        name,
        cloneFrom: cloneFromId || undefined,
      });
      setShowCreate(false);
      setNewName('');
      setCloneFromId('');
      // Reload and select the new worker
      void listWorkers(workerTypeMap[tab]).then((w) => {
        setWorkers(w);
        setSelectedWorkerId(created.id);
      });
      // Refresh agent list in case a new Agent was created
      void listWorkers('Agent').then(setAllAgents).catch(() => {});
    } catch (e) {
      setCreateError(e instanceof Error ? e.message : 'Failed to create');
    } finally {
      setCreating(false);
    }
  }, [newName, cloneFromId, tab]);

  const openCreate = useCallback(() => {
    setNewName('');
    setCloneFromId(workers.length > 0 ? workers[0].id : '');
    setCreateError('');
    setShowCreate(true);
  }, [workers]);

  return (
    <section className="page-frame workers-frame">
      <header className="page-header">
        <div>
          <h1>{t('workers.title')}</h1>
          <p>{t('workers.subtitle')}</p>
        </div>
      </header>

      <div className="tabs" role="tablist">
        {(['Agents', 'Teams'] as WorkerTab[]).map((item) => (
          <button
            key={item}
            type="button"
            role="tab"
            aria-selected={tab === item}
            className={tab === item ? 'tab active' : 'tab'}
            onClick={() => setTab(item)}
          >
            {t(tabI18nKeys[item])}
          </button>
        ))}
      </div>

      <div className="workers-settings-layout">
        <div className="workers-list-panel">
          <button
            type="button"
            className="worker-add-btn"
            onClick={openCreate}
          >
            + {t('workers.add')}
          </button>

          {workers.map((w) => (
            <button
              key={w.id}
              type="button"
              className={`worker-list-item ${w.id === selectedWorkerId ? 'active' : ''}`}
              onClick={() => setSelectedWorkerId(w.id)}
            >
              <span className={`worker-badge ${w.type.toLowerCase()}`}>{w.type}</span>
              <div className="worker-list-item-info">
                <strong>{w.name}</strong>
                <span>
                  {w.description.slice(0, 50)}
                  {w.description.length > 50 ? '...' : ''}
                </span>
              </div>
            </button>
          ))}
          {workers.length === 0 && <p className="skill-empty">{t('workers.noItems', { type: t(tabI18nKeys[tab]).toLowerCase() })}</p>}
        </div>

        {selectedWorker && (
          <div className="worker-settings-panel">
            <div className="settings-header">
              <div className="settings-name-row">
                <span className="settings-name-display">{selectedWorker.name}</span>
                <span className={`worker-badge ${selectedWorker.type.toLowerCase()}`}>
                  {selectedWorker.type}
                </span>
              </div>
              <span className="settings-desc-display">{selectedWorker.description}</span>
            </div>

            <div className="settings-content-area">
              <WorkerSettingsPanel
                worker={selectedWorker}
                navLayout="vertical"
                allAgents={allAgents}
                onSave={(saved) => {
                  setWorkers((current) =>
                    current.map((item) => (item.id === saved.id ? saved : item)),
                  );
                  onWorkerUpdate?.(saved);
                }}
              />
            </div>
          </div>
        )}
      </div>

      {/* Create dialog */}
      {showCreate && (
        <div className="modal-overlay" onClick={() => setShowCreate(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <h3>{t('workers.createTitle')}</h3>

            <label className="modal-field">
              <span>{t('workers.nameLabel')} *</span>
              <input
                className="settings-input"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder={t('workers.namePlaceholder')}
                autoFocus
                onKeyDown={(e) => { if (e.key === 'Enter') void handleCreate(); }}
              />
            </label>

            <label className="modal-field">
              <span>{t('workers.cloneLabel')}</span>
              <select
                className="settings-input"
                value={cloneFromId}
                onChange={(e) => setCloneFromId(e.target.value)}
              >
                <option value="">{t('workers.cloneNone')}</option>
                {workers.map((w) => (
                  <option key={w.id} value={w.id}>{w.name}</option>
                ))}
              </select>
            </label>

            {createError && <p className="modal-error">{createError}</p>}

            <div className="modal-actions">
              <button type="button" className="btn-secondary" onClick={() => setShowCreate(false)}>
                {t('workers.cancel')}
              </button>
              <button
                type="button"
                className="btn-primary"
                disabled={!newName.trim() || creating}
                onClick={() => void handleCreate()}
              >
                {creating ? '...' : t('workers.createBtn')}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
