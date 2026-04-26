import { useMemo, useState } from 'react';
import { useI18n } from '../i18n';
import type { WorkerSummary } from '../types';

interface WorkerListProps {
  workers: WorkerSummary[];
  activeWorkerId?: string;
  runningWorkerIds?: Set<string>;
  onSelect: (workerId: string) => void;
}

function parseRecentTime(value?: string | null): number {
  if (!value) return 0;
  const numeric = Number(value);
  if (!Number.isNaN(numeric) && numeric > 0) {
    return numeric > 1e12 ? numeric : numeric * 1000;
  }
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? 0 : parsed;
}

function formatRecentTime(value: string | undefined, locale: string): string | null {
  const timestamp = parseRecentTime(value);
  if (!timestamp) return null;

  const diffMs = timestamp - Date.now();
  const absMs = Math.abs(diffMs);
  const minute = 60 * 1000;
  const hour = 60 * minute;
  const day = 24 * hour;
  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' });

  if (absMs < hour) {
    return rtf.format(Math.round(diffMs / minute), 'minute');
  }
  if (absMs < day) {
    return rtf.format(Math.round(diffMs / hour), 'hour');
  }
  if (absMs < 7 * day) {
    return rtf.format(Math.round(diffMs / day), 'day');
  }

  return new Intl.DateTimeFormat(locale, {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(timestamp));
}

export function WorkerList({ workers, activeWorkerId, runningWorkerIds = new Set(), onSelect }: WorkerListProps) {
  const { t, locale } = useI18n();
  const [showSearch, setShowSearch] = useState(false);
  const [query, setQuery] = useState('');

  const filteredWorkers = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    if (!keyword) return workers;
    return workers.filter((worker) => {
      const haystack = [worker.name, worker.description, worker.type]
        .join(' ')
        .toLowerCase();
      return haystack.includes(keyword);
    });
  }, [query, workers]);

  return (
    <section className="worker-panel">
      <header className="worker-panel-header">
        <div>
          <h2>{t('workerList.title')}</h2>
          <p>{t('workerList.subtitle')}</p>
        </div>
        <button
          type="button"
          className={`worker-search-toggle ${showSearch ? 'active' : ''}`}
          onClick={() => {
            if (showSearch && query) {
              setQuery('');
            }
            setShowSearch((current) => !current);
          }}
        >
          <span aria-hidden="true">⌕</span>
          {t('workerList.search')}
        </button>
      </header>

      {showSearch && (
        <div className="worker-search-bar">
          <input
            type="text"
            className="worker-search-input"
            placeholder={t('workerList.searchPlaceholder')}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
      )}

      <div className="worker-items">
        {filteredWorkers.length > 0 ? filteredWorkers.map((worker) => {
          const recentLabel = formatRecentTime(worker.recent, locale);
          return (
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
                {recentLabel && (
                  <span className="worker-recent" title={worker.recent || recentLabel}>
                    {recentLabel}
                  </span>
                )}
              </div>
            </button>
          );
        }) : (
          <div className="worker-empty-state">{t('workerList.noMatch')}</div>
        )}
      </div>
    </section>
  );
}
