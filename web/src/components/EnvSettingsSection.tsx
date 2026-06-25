import { useEffect, useMemo, useState } from 'react';
import { useI18n } from '../i18n';
import {
  applyEnvironmentVariables,
  getEnvironmentVariables,
  saveEnvironmentVariables,
} from '../lib/backend';

type EnvEntry = {
  readonly id: string;
  readonly originalName: string;
  readonly name: string;
  readonly value: string;
};

type SavedEnvEntry = {
  readonly name: string;
  readonly value: string;
};

function makeId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function toEntry(name: string, value: string): EnvEntry {
  return {
    id: makeId(),
    originalName: name,
    name,
    value,
  };
}

export function EnvSettingsSection() {
  const { t } = useI18n();
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [applying, setApplying] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [message, setMessage] = useState('');
  const [entries, setEntries] = useState<readonly EnvEntry[]>([]);
  const [removedNames, setRemovedNames] = useState<readonly string[]>([]);
  const [newName, setNewName] = useState('');
  const [newValue, setNewValue] = useState('');

  useEffect(() => {
    let cancelled = false;

    async function loadEnv() {
      try {
        const res = await getEnvironmentVariables();
        if (cancelled) return;
        setEntries(res.variables.map((item) => toEntry(item.name, item.value)));
      } catch {
        if (!cancelled) setEntries([]);
      } finally {
        if (!cancelled) setLoaded(true);
      }
    }

    void loadEnv();
    return () => {
      cancelled = true;
    };
  }, []);

  const normalizedEntries = useMemo(() => entries.filter((entry) => entry.name.trim()), [entries]);

  function updateEntry(id: string, patch: Partial<Pick<EnvEntry, 'name' | 'value'>>) {
    setEntries((current) => current.map((entry) => (entry.id === id ? { ...entry, ...patch } : entry)));
    setDirty(true);
  }

  function removeEntry(id: string) {
    setEntries((current) => {
      const target = current.find((entry) => entry.id === id);
      if (target) {
        setRemovedNames((names) => (names.includes(target.originalName) ? names : [...names, target.originalName]));
      }
      return current.filter((entry) => entry.id !== id);
    });
    setDirty(true);
  }

  function addEntry() {
    const name = newName.trim();
    if (!name) return;
    setEntries((current) => [...current, toEntry(name, newValue)]);
    setNewName('');
    setNewValue('');
    setDirty(true);
  }

  function buildChanges(): Record<string, string | null> {
    const changes: Record<string, string | null> = {};
    for (const entry of normalizedEntries) {
      changes[entry.name.trim()] = entry.value;
      if (entry.originalName !== entry.name.trim() && entry.originalName.trim()) {
        changes[entry.originalName] = null;
      }
    }
    for (const name of removedNames) {
      changes[name] = null;
    }
    return changes;
  }

  function rebuildEntries(next: readonly SavedEnvEntry[]) {
    setEntries(next.map((item) => toEntry(item.name, item.value)));
  }

  async function handleSave() {
    setSaving(true);
    setMessage('');
    try {
      const saved = await saveEnvironmentVariables(buildChanges());
      rebuildEntries(saved.variables.map((item) => ({ name: item.name, value: item.value })));
      setRemovedNames([]);
      setDirty(false);
      setMessage(t('settings.envSaved'));
    } catch {
      setMessage(t('settings.envSaveError'));
    } finally {
      setSaving(false);
    }
  }

  async function handleApply() {
    setApplying(true);
    setMessage('');
    try {
      if (dirty) {
        const saved = await saveEnvironmentVariables(buildChanges());
        rebuildEntries(saved.variables.map((item) => ({ name: item.name, value: item.value })));
        setRemovedNames([]);
        setDirty(false);
      }
      const applied = await applyEnvironmentVariables();
      setMessage(t('settings.envApplied', { count: applied.reloadedWorkers.length }));
    } catch {
      setMessage(t('settings.envApplyError'));
    } finally {
      setApplying(false);
    }
  }

  return (
    <section className="settings-block">
      <h3 className="settings-block-title">{t('settings.envTitle')}</h3>
      <div className="settings-block-body">
        <p className="settings-section-desc">{t('settings.envHint')}</p>
        <div className="settings-form" style={{ gap: '10px' }}>
          {entries.length === 0 && loaded && (
            <p className="settings-section-desc">{t('settings.envEmpty')}</p>
          )}
          {entries.map((entry) => (
            <div key={entry.id} style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
              <input
                className="settings-input"
                style={{ flex: 0.8 }}
                value={entry.name}
                placeholder={t('settings.envName')}
                onChange={(e) => updateEntry(entry.id, { name: e.target.value })}
              />
              <input
                className="settings-input"
                style={{ flex: 1.2 }}
                value={entry.value}
                placeholder={t('settings.envValue')}
                onChange={(e) => updateEntry(entry.id, { value: e.target.value })}
              />
              <button type="button" className="soft-button" onClick={() => removeEntry(entry.id)}>
                {t('settings.envRemove')}
              </button>
            </div>
          ))}
          <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
            <input
              className="settings-input"
              style={{ flex: 0.8 }}
              value={newName}
              placeholder={t('settings.envName')}
              onChange={(e) => setNewName(e.target.value)}
            />
            <input
              className="settings-input"
              style={{ flex: 1.2 }}
              value={newValue}
              placeholder={t('settings.envValue')}
              onChange={(e) => setNewValue(e.target.value)}
            />
            <button type="button" className="soft-button" onClick={addEntry} disabled={!newName.trim()}>
              {t('settings.envAdd')}
            </button>
          </div>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', marginTop: '8px' }}>
          <span className="settings-section-desc" style={{ margin: 0 }}>
            {message || (dirty ? t('settings.envDirty') : '')}
          </span>
          <div style={{ display: 'flex', gap: '8px' }}>
            <button type="button" className="soft-button" disabled={saving || applying || (!dirty && entries.length === 0)} onClick={() => void handleSave()}>
              {saving ? t('settings.saving') : t('settings.envSave')}
            </button>
            <button type="button" className="primary-button" disabled={applying} onClick={() => void handleApply()}>
              {applying ? t('settings.applying') : t('settings.envApply')}
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}
