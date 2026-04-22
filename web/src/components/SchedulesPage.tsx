import { useCallback, useEffect, useMemo, useState } from 'react';
import { useI18n } from '../i18n';
import { createSchedule, deleteSchedule, listScheduleRuns, listSchedules, listWorkers, runSchedule, updateSchedule, type SchedulePayload } from '../lib/backend';
import type { ScheduleRun, ScheduleSummary, WorkerSummary, WorkspaceBinding } from '../types';

const WEEKDAY_OPTIONS = [
  { value: 0, label: 'Mon' },
  { value: 1, label: 'Tue' },
  { value: 2, label: 'Wed' },
  { value: 3, label: 'Thu' },
  { value: 4, label: 'Fri' },
  { value: 5, label: 'Sat' },
  { value: 6, label: 'Sun' },
];

function defaultTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

function emptySchedule(workerId = ''): SchedulePayload {
  return {
    name: '',
    enabled: true,
    workerId,
    prompt: '',
    sessionTitleTemplate: '',
    workspaces: null,
    triggerType: 'daily',
    time: '09:00',
    weekdays: [0],
    timezone: defaultTimezone(),
    misfirePolicy: 'run_once',
    createNewSession: true,
  };
}

function formatDateTime(value?: string | null): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function formatRule(schedule: Pick<ScheduleSummary, 'triggerType' | 'time' | 'weekdays'>): string {
  if (schedule.triggerType === 'daily') return `Every day ${schedule.time}`;
  const labels = WEEKDAY_OPTIONS.filter((item) => (schedule.weekdays ?? []).includes(item.value)).map((item) => item.label);
  return `Weekly ${labels.join(', ')} ${schedule.time}`;
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

interface SchedulesPageProps {
  onOpenChatSession?: (workerId: string, sessionId?: string | null) => void;
}

export function SchedulesPage({ onOpenChatSession }: SchedulesPageProps) {
  const { t } = useI18n();
  const [workers, setWorkers] = useState<WorkerSummary[]>([]);
  const [schedules, setSchedules] = useState<ScheduleSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [form, setForm] = useState<SchedulePayload>(emptySchedule());
  const [runs, setRuns] = useState<ScheduleRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [dirty, setDirty] = useState(false);
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'idle' | 'success' | 'failed' | 'running'>('all');
  const [workerFilter, setWorkerFilter] = useState<'all' | string>('all');
  const [enabledOnly, setEnabledOnly] = useState(false);

  const reload = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [workersResp, schedulesResp] = await Promise.all([listWorkers(), listSchedules()]);
      setWorkers(workersResp);
      setSchedules(schedulesResp);
      setSelectedId((current) => {
        const nextSelectedId = schedulesResp.find((item) => item.id === current)?.id ?? schedulesResp[0]?.id ?? null;
        if (!nextSelectedId) {
          setForm(emptySchedule(workersResp[0]?.id ?? ''));
        }
        return nextSelectedId;
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load schedules');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const filteredSchedules = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    return schedules.filter((schedule) => {
      if (enabledOnly && !schedule.enabled) return false;
      if (statusFilter !== 'all' && (schedule.lastStatus ?? 'idle') !== statusFilter) return false;
      if (workerFilter !== 'all' && schedule.workerId !== workerFilter) return false;
      if (!keyword) return true;
      const haystack = [schedule.name, schedule.prompt, schedule.workerName ?? '', schedule.workerId].join(' ').toLowerCase();
      return haystack.includes(keyword);
    });
  }, [enabledOnly, query, schedules, statusFilter, workerFilter]);

  const selectedSchedule = useMemo(() => schedules.find((item) => item.id === selectedId) ?? null, [schedules, selectedId]);
  const latestSessionRun = useMemo(() => runs.find((run) => Boolean(run.sessionId)) ?? null, [runs]);
  const selectedWorker = useMemo(() => workers.find((item) => item.id === form.workerId) ?? null, [form.workerId, workers]);
  const workerWorkspaces = useMemo(() => getWorkerWorkspaces(selectedWorker), [selectedWorker]);
  const effectiveWorkspaces = useMemo(() => {
    const allPaths = workerWorkspaces.map((item) => item.path);
    return form.workspaces && form.workspaces.length > 0 ? form.workspaces : allPaths;
  }, [form.workspaces, workerWorkspaces]);

  useEffect(() => {
    if (!selectedSchedule) {
      setRuns([]);
      return;
    }
    setForm({
      name: selectedSchedule.name,
      enabled: selectedSchedule.enabled,
      workerId: selectedSchedule.workerId,
      prompt: selectedSchedule.prompt,
      sessionTitleTemplate: selectedSchedule.sessionTitleTemplate ?? '',
      workspaces: selectedSchedule.workspaces ?? null,
      triggerType: selectedSchedule.triggerType,
      time: selectedSchedule.time,
      weekdays: selectedSchedule.weekdays ?? [0],
      timezone: selectedSchedule.timezone,
      misfirePolicy: selectedSchedule.misfirePolicy,
      createNewSession: selectedSchedule.createNewSession,
    });
    setDirty(false);
    void listScheduleRuns(selectedSchedule.id).then(setRuns).catch(() => setRuns([]));
  }, [selectedSchedule]);

  const handleCreateNew = useCallback(() => {
    setSelectedId(null);
    setForm(emptySchedule(workers[0]?.id ?? ''));
    setRuns([]);
    setDirty(false);
    setError('');
  }, [workers]);

  const updateForm = useCallback(<K extends keyof SchedulePayload>(key: K, value: SchedulePayload[K]) => {
    setForm((current) => ({ ...current, [key]: value }));
    setDirty(true);
  }, []);

  const toggleWeekday = useCallback((value: number) => {
    setForm((current) => {
      const currentDays = current.weekdays ?? [];
      const nextDays = currentDays.includes(value)
        ? currentDays.filter((item) => item !== value)
        : [...currentDays, value].sort((a, b) => a - b);
      return { ...current, weekdays: nextDays };
    });
    setDirty(true);
  }, []);

  const toggleWorkspace = useCallback((path: string) => {
    setForm((current) => {
      const allPaths = workerWorkspaces.map((item) => item.path);
      const currentPaths = current.workspaces && current.workspaces.length > 0 ? current.workspaces : allPaths;
      const exists = currentPaths.includes(path);
      const nextPaths = exists ? currentPaths.filter((item) => item !== path) : [...currentPaths, path];
      const safePaths = nextPaths.length === 0 ? allPaths : nextPaths;
      return {
        ...current,
        workspaces: safePaths.length === allPaths.length ? null : safePaths,
      };
    });
    setDirty(true);
  }, [workerWorkspaces]);

  const handleSave = useCallback(async () => {
    setSaving(true);
    setError('');
    try {
      const payload: SchedulePayload = {
        ...form,
        workspaces: form.workspaces && form.workspaces.length > 0 ? form.workspaces : null,
        weekdays: form.triggerType === 'weekly' ? (form.weekdays ?? []) : [],
      };
      const saved = selectedId ? await updateSchedule(selectedId, payload) : await createSchedule(payload);
      const refreshed = await listSchedules();
      setSchedules(refreshed);
      setSelectedId(saved.id);
      setDirty(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save schedule');
    } finally {
      setSaving(false);
    }
  }, [form, selectedId]);

  const handleDelete = useCallback(async () => {
    if (!selectedId) return;
    if (!window.confirm('Delete this schedule?')) return;
    setSaving(true);
    setError('');
    try {
      await deleteSchedule(selectedId);
      const refreshed = await listSchedules();
      setSchedules(refreshed);
      const nextId = refreshed[0]?.id ?? null;
      setSelectedId(nextId);
      if (!nextId) {
        setForm(emptySchedule(workers[0]?.id ?? ''));
        setRuns([]);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to delete schedule');
    } finally {
      setSaving(false);
    }
  }, [selectedId, workers]);

  const handleRunNow = useCallback(async () => {
    if (!selectedId) return;
    setSaving(true);
    setError('');
    try {
      await runSchedule(selectedId);
      const [refreshedSchedules, refreshedRuns] = await Promise.all([listSchedules(), listScheduleRuns(selectedId)]);
      setSchedules(refreshedSchedules);
      setRuns(refreshedRuns);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to run schedule');
    } finally {
      setSaving(false);
    }
  }, [selectedId]);

  const handleRetryLatest = useCallback(async () => {
    if (!selectedId) return;
    await handleRunNow();
  }, [handleRunNow, selectedId]);

  const handleToggleEnabled = useCallback(async (enabled: boolean) => {
    if (!selectedId) return;
    setSaving(true);
    setError('');
    try {
      const payload: SchedulePayload = {
        ...form,
        enabled,
        workspaces: form.workspaces && form.workspaces.length > 0 ? form.workspaces : null,
        weekdays: form.triggerType === 'weekly' ? (form.weekdays ?? []) : [],
      };
      const saved = await updateSchedule(selectedId, payload);
      const refreshed = await listSchedules();
      setSchedules(refreshed);
      setSelectedId(saved.id);
      setForm((current) => ({ ...current, enabled }));
      setDirty(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to update schedule state');
    } finally {
      setSaving(false);
    }
  }, [form, selectedId]);

  return (
    <section className="page-frame schedules-page">
      <header className="page-header">
        <div>
          <h2>{t('schedules.title')}</h2>
          <p>{t('schedules.subtitle')}</p>
        </div>
        <div className="page-actions">
          <button type="button" className="soft-button" onClick={() => void reload()} disabled={loading || saving}>{t('schedules.refresh')}</button>
          <button type="button" className="primary-button" onClick={handleCreateNew}>{t('schedules.newSchedule')}</button>
        </div>
      </header>

      <div className="schedule-filter-bar form-card">
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t('schedules.search')} />
        <select value={workerFilter} onChange={(e) => setWorkerFilter(e.target.value)}>
          <option value="all">{t('schedules.allWorkers')}</option>
          {workers.map((worker) => <option key={worker.id} value={worker.id}>{worker.name}</option>)}
        </select>
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as 'all' | 'idle' | 'success' | 'failed' | 'running')}>
          <option value="all">{t('schedules.allStatus')}</option>
          <option value="idle">{t('schedules.idle')}</option>
          <option value="running">{t('schedules.running')}</option>
          <option value="success">{t('schedules.success')}</option>
          <option value="failed">{t('schedules.failed')}</option>
        </select>
        <label className="schedule-filter-check">
          <input type="checkbox" checked={enabledOnly} onChange={(e) => setEnabledOnly(e.target.checked)} />
          <span>{t('schedules.enabledOnly')}</span>
        </label>
      </div>

      <div className="schedules-layout">
        <aside className="schedule-list-panel">
          {loading ? <p className="helper-text">Loading…</p> : null}
          {!loading && schedules.length === 0 ? <p className="helper-text">{t('schedules.noSchedules')}</p> : null}
          {!loading && schedules.length > 0 && filteredSchedules.length === 0 ? <p className="helper-text">{t('schedules.noMatch')}</p> : null}
          {filteredSchedules.map((schedule) => (
            <button
              key={schedule.id}
              type="button"
              className={selectedId === schedule.id ? 'schedule-list-item active' : 'schedule-list-item'}
              onClick={() => setSelectedId(schedule.id)}
            >
              <div className="schedule-list-top">
                <strong>{schedule.name}</strong>
                <span className={`schedule-status ${schedule.lastStatus ?? 'idle'}`}>{schedule.lastStatus ?? 'idle'}</span>
              </div>
              <div className="schedule-list-meta">{schedule.workerName || schedule.workerId}</div>
              <div className="schedule-list-meta">{schedule.enabled ? t('schedules.enabled') : t('schedules.paused')}</div>
              <div className="schedule-list-meta">{formatRule(schedule)}</div>
              <div className="schedule-list-meta">{t('schedules.next', { time: formatDateTime(schedule.nextRunAt) })}</div>
            </button>
          ))}
        </aside>

        <div className="schedule-editor-panel">
          {error ? <div className="form-error">{error}</div> : null}

          <div className="form-card schedule-editor-grid">
            <label>
              <span>{t('schedules.name')}</span>
              <input value={form.name} onChange={(e) => updateForm('name', e.target.value)} placeholder="Morning summary" />
            </label>
            <label>
              <span>{t('schedules.worker')}</span>
              <select value={form.workerId} onChange={(e) => updateForm('workerId', e.target.value)}>
                <option value="">{t('schedules.selectWorker')}</option>
                {workers.map((worker) => <option key={worker.id} value={worker.id}>{worker.name}</option>)}
              </select>
            </label>
            <label className="checkbox-row">
              <input type="checkbox" checked={form.enabled} onChange={(e) => updateForm('enabled', e.target.checked)} />
              <span>{t('schedules.enabledLabel')}</span>
            </label>
            <label>
              <span>{t('schedules.timezone')}</span>
              <input value={form.timezone} onChange={(e) => updateForm('timezone', e.target.value)} placeholder="Asia/Shanghai" />
            </label>
            <label className="schedule-full-row">
              <span>{t('schedules.prompt')}</span>
              <textarea rows={8} value={form.prompt} onChange={(e) => updateForm('prompt', e.target.value)} placeholder="What should the worker do when the schedule fires?" />
            </label>
            <label className="schedule-full-row">
              <span>{t('schedules.sessionTitle')}</span>
              <input
                value={form.sessionTitleTemplate ?? ''}
                onChange={(e) => updateForm('sessionTitleTemplate', e.target.value)}
                placeholder="{name} - {date} {time}"
              />
              <span className="helper-text">{t('schedules.placeholders')}</span>
            </label>
            <label>
              <span>{t('schedules.trigger')}</span>
              <select value={form.triggerType} onChange={(e) => updateForm('triggerType', e.target.value as 'daily' | 'weekly')}>
                <option value="daily">{t('schedules.daily')}</option>
                <option value="weekly">{t('schedules.weekly')}</option>
              </select>
            </label>
            <label>
              <span>{t('schedules.time')}</span>
              <input type="time" value={form.time} onChange={(e) => updateForm('time', e.target.value)} />
            </label>
            <label>
              <span>{t('schedules.missedPolicy')}</span>
              <select value={form.misfirePolicy} onChange={(e) => updateForm('misfirePolicy', e.target.value as 'skip' | 'run_once')}>
                <option value="run_once">{t('schedules.runOnce')}</option>
                <option value="skip">{t('schedules.skipMissed')}</option>
              </select>
            </label>
            <label className="checkbox-row">
              <input type="checkbox" checked={form.createNewSession} onChange={(e) => updateForm('createNewSession', e.target.checked)} />
              <span>{t('schedules.createNewSession')}</span>
            </label>

            {form.triggerType === 'weekly' && (
              <div className="schedule-full-row">
                <span className="input-label">{t('schedules.weekdays')}</span>
                <div className="weekday-pills">
                  {WEEKDAY_OPTIONS.map((day) => {
                    const active = (form.weekdays ?? []).includes(day.value);
                    return (
                      <button key={day.value} type="button" className={active ? 'weekday-pill active' : 'weekday-pill'} onClick={() => toggleWeekday(day.value)}>
                        {day.label}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            <div className="schedule-full-row">
              <span className="input-label">{t('schedules.workspaces')}</span>
              {workerWorkspaces.length === 0 ? (
                <div className="helper-text">{t('schedules.noWorkspaces')}</div>
              ) : (
                <div className="ws-check-list">
                  {workerWorkspaces.map((ws) => {
                    const checked = effectiveWorkspaces.includes(ws.path);
                    return (
                      <label key={ws.path} className="ws-check-item" title={ws.path}>
                        <input type="checkbox" checked={checked} onChange={() => toggleWorkspace(ws.path)} />
                        <span className="ws-check-name">{ws.path.replace(/\\/g, '/').split('/').filter(Boolean).pop() || ws.path}</span>
                      </label>
                    );
                  })}
                </div>
              )}
            </div>

            <div className="schedule-full-row schedule-actions-row">
              <button type="button" className="primary-button" onClick={() => void handleSave()} disabled={saving || !form.workerId || !form.prompt.trim()}>
                {selectedId ? 'Save Changes' : 'Create Schedule'}
              </button>
              {selectedId ? <button type="button" className="soft-button" onClick={() => void handleRunNow()} disabled={saving}>{t('schedules.runNow')}</button> : null}
              {selectedId ? (
                <button
                  type="button"
                  className="soft-button"
                  onClick={() => void handleToggleEnabled(!form.enabled)}
                  disabled={saving}
                >
                  {form.enabled ? 'Pause Schedule' : 'Resume Schedule'}
                </button>
              ) : null}
              {selectedId && selectedSchedule?.lastStatus === 'failed' ? <button type="button" className="soft-button" onClick={() => void handleRetryLatest()} disabled={saving}>{t('schedules.retryFailed')}</button> : null}
              {selectedId && latestSessionRun?.sessionId && onOpenChatSession ? (
                <button type="button" className="soft-button" onClick={() => onOpenChatSession(latestSessionRun.workerId, latestSessionRun.sessionId)}>
                  Open Latest Session
                </button>
              ) : null}
              {selectedId && onOpenChatSession ? <button type="button" className="soft-button" onClick={() => onOpenChatSession(form.workerId)} disabled={!form.workerId}>{t('schedules.openWorkerChat')}</button> : null}
              {selectedId ? <button type="button" className="cancel-button" onClick={() => void handleDelete()} disabled={saving}>{t('schedules.delete')}</button> : null}
              {dirty ? <span className="helper-text">{t('schedules.unsavedChanges')}</span> : null}
            </div>
          </div>

          <div className="form-card schedule-runs-card">
            <div className="canvas-header">
              <h3>{t('schedules.recentRuns')}</h3>
              <span className="helper-text">{selectedSchedule ? formatRule(selectedSchedule) : t('schedules.selectOrCreate')}</span>
            </div>
            {runs.length === 0 ? <div className="helper-text">{t('schedules.noRuns')}</div> : null}
            <div className="schedule-runs-list">
              {runs.map((run) => (
                <div key={run.id} className="schedule-run-row">
                  <div>
                    <div className="schedule-run-top">
                      <strong>{run.status}</strong>
                      <span>{formatDateTime(run.startedAt || run.plannedAt)}</span>
                    </div>
                    <div className="schedule-run-meta">{t('schedules.planned', { time: formatDateTime(run.plannedAt) })}</div>
                    {run.sessionId ? <div className="schedule-run-meta">{t('schedules.session', { id: run.sessionId })}</div> : null}
                    <div className="schedule-run-actions">
                      {run.sessionId && onOpenChatSession ? (
                        <button type="button" className="soft-button" onClick={() => onOpenChatSession(run.workerId, run.sessionId)}>
                          Open Session
                        </button>
                      ) : null}
                      {selectedId ? (
                        <button type="button" className="soft-button" onClick={() => void handleRunNow()} disabled={saving}>
                          Run Again
                        </button>
                      ) : null}
                    </div>
                    {run.error ? <div className="schedule-run-error">{run.error}</div> : null}
                    {run.outputPreview ? <div className="schedule-run-preview">{run.outputPreview}</div> : null}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
