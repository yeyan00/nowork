/**
 * WorkersManager — worker studio page.
 * Uses the shared WorkerSettingsPanel for the settings area.
 */

import { useEffect, useState } from 'react';
import { useI18n } from '../i18n';
import {
  listWorkers,
} from '../lib/backend';
import type { WorkerSummary } from '../types';
import { WorkerSettingsPanel } from './WorkerSettingsPanel';

type WorkerTab = 'Agents' | 'Teams' | 'Workflows';

const workerTypeMap: Record<WorkerTab, WorkerSummary['type']> = {
  Agents: 'Agent',
  Teams: 'Team',
  Workflows: 'Workflow',
};

const tabI18nKeys: Record<WorkerTab, string> = {
  Agents: 'workers.agents',
  Teams: 'workers.teams',
  Workflows: 'workers.workflows',
};

export function WorkersManager() {
  const { t } = useI18n();
  const [tab, setTab] = useState<WorkerTab>('Agents');
  const [workers, setWorkers] = useState<WorkerSummary[]>([]);
  const [selectedWorkerId, setSelectedWorkerId] = useState<string | null>(null);
  const [allAgents, setAllAgents] = useState<WorkerSummary[]>([]);

  useEffect(() => {
    void listWorkers(workerTypeMap[tab]).then((w) => {
      setWorkers(w);
      setSelectedWorkerId(w.length > 0 ? w[0].id : null);
    });
  }, [tab]);

  useEffect(() => {
    void listWorkers('Agent').then(setAllAgents).catch(() => {});
  }, []);

  const selectedWorker = workers.find((item) => item.id === selectedWorkerId) ?? null;

  return (
    <section className="page-frame workers-frame">
      <header className="page-header">
        <div>
          <h1>{t('workers.title')}</h1>
          <p>{t('workers.subtitle')}</p>
        </div>
      </header>

      <div className="tabs" role="tablist">
        {(['Agents', 'Teams', 'Workflows'] as WorkerTab[]).map((item) => (
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
                }}
              />
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
