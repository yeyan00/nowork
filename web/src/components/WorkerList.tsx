import { useI18n } from '../i18n';
import type { WorkerSummary } from '../types';

interface WorkerListProps {
  workers: WorkerSummary[];
  activeWorkerId?: string;
  runningWorkerIds?: Set<string>;
  onSelect: (workerId: string) => void;
}

export function WorkerList({ workers, activeWorkerId, runningWorkerIds = new Set(), onSelect }: WorkerListProps) {
  const { t } = useI18n();

  return (
    <section className="worker-panel">
      <header className="worker-panel-header">
        <div>
          <h2>{t('workerList.title')}</h2>
          <p>{t('workerList.subtitle')}</p>
        </div>
        <button type="button" className="soft-button">
          {t('workerList.filter')}
        </button>
      </header>

      <div className="worker-items">
        {workers.map((worker) => (
          <button
            key={worker.id}
            type="button"
            className={worker.id === activeWorkerId ? 'worker-item active' : 'worker-item'}
            onClick={() => onSelect(worker.id)}
          >
            <div className={`worker-icon ${worker.type.toLowerCase()}`}>{worker.type.slice(0, 1)}</div>
            <div className="worker-body">
              <div className="worker-row">
                <strong className="worker-name" title={worker.name}>{worker.name}</strong>
                {runningWorkerIds.has(worker.id) && <span className="worker-running-dot" aria-label="Worker is running" />}
              </div>
              <span className="worker-summary" title={worker.description}>{worker.description}</span>
            </div>
          </button>
        ))}
      </div>
    </section>
  );
}
