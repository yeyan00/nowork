import { useEffect, useState, useCallback } from 'react';
import { useI18n } from '../i18n';
import type { ChannelSummary, ChannelPlatform, WorkerSummary } from '../types';

const API = '/api';

async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(url, init);
  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`${resp.status}: ${body}`);
  }
  return resp.json();
}

const PLATFORM_ICONS: Record<string, string> = {
  dingtalk: '📌',
  feishu: '🐦',
  wecom: '💼',
};

interface ConfigField {
  key: string;
  labelKey: string;
  type: 'text' | 'password' | 'select';
  required?: boolean;
  options?: Array<{ value: string; labelKey: string }>;
}

const PLATFORM_CONFIG_FIELDS: Record<string, ConfigField[]> = {
  dingtalk: [
    { key: 'client_id', labelKey: 'channels.clientId', type: 'text', required: true },
    { key: 'client_secret', labelKey: 'channels.clientSecret', type: 'password', required: true },
    { key: 'robot_code', labelKey: 'channels.robotCode', type: 'text' },
    {
      key: 'message_type', labelKey: 'channels.messageType', type: 'select',
      options: [
        { value: 'markdown', labelKey: 'channels.markdown' },
        { value: 'text', labelKey: 'channels.text' },
      ],
    },
  ],
  feishu: [
    { key: 'app_id', labelKey: 'channels.appId', type: 'text', required: true },
    { key: 'app_secret', labelKey: 'channels.appSecret', type: 'password', required: true },
    {
      key: 'domain', labelKey: 'channels.domain', type: 'select',
      options: [
        { value: 'feishu', labelKey: 'channels.feishu' },
        { value: 'lark', labelKey: 'Lark' },
      ],
    },
  ],
  wecom: [
    { key: 'bot_id', labelKey: 'channels.botId', type: 'text', required: true },
    { key: 'secret', labelKey: 'channels.secret', type: 'password', required: true },
  ],
};

export function ChannelsPage() {
  const { t } = useI18n();
  const [channels, setChannels] = useState<ChannelSummary[]>([]);
  const [platforms, setPlatforms] = useState<ChannelPlatform[]>([]);
  const [workers, setWorkers] = useState<WorkerSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<ChannelSummary | null>(null);
  const [isNew, setIsNew] = useState(false);
  const [form, setForm] = useState<Record<string, unknown>>({});
  const [saving, setSaving] = useState(false);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [ch, pl, wk] = await Promise.all([
        fetchJSON<ChannelSummary[]>(`${API}/channels`),
        fetchJSON<ChannelPlatform[]>(`${API}/channels/platforms`),
        fetchJSON<WorkerSummary[]>(`${API}/workers`),
      ]);
      setChannels(ch);
      setPlatforms(pl);
      setWorkers(wk);
    } catch (e) {
      console.error('Failed to load channels:', e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  const openNew = () => {
    setIsNew(true);
    setEditing(null);
    setForm({ id: '', platform: '', name: '', enabled: false, worker_id: '', config: {} });
  };

  const openEdit = (ch: ChannelSummary) => {
    setIsNew(false);
    setEditing(ch);
    setForm({ ...ch });
  };

  const closeDrawer = () => {
    setEditing(null);
    setIsNew(false);
    setForm({});
  };

  const updateForm = (key: string, value: unknown) => {
    setForm(prev => ({ ...prev, [key]: value }));
  };

  const updateConfig = (key: string, value: unknown) => {
    const config = { ...(form.config as Record<string, unknown> || {}) };
    config[key] = value;
    setForm(prev => ({ ...prev, config }));
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const payload = {
        id: form.id,
        platform: form.platform,
        name: form.name,
        enabled: form.enabled,
        worker_id: form.worker_id,
        config: form.config,
      };
      if (isNew) {
        await fetchJSON(`${API}/channels`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
      } else {
        await fetchJSON(`${API}/channels/${form.id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
      }
      closeDrawer();
      loadData();
    } catch (e) {
      console.error('Save failed:', e);
      alert(`Save failed: ${e}`);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm(`Delete channel "${id}"?`)) return;
    try {
      await fetchJSON(`${API}/channels/${id}`, { method: 'DELETE' });
      closeDrawer();
      loadData();
    } catch (e) {
      console.error('Delete failed:', e);
    }
  };

  const handleTest = async (id: string) => {
    try {
      const result = await fetchJSON<{ ok: boolean; error?: string }>(`${API}/channels/${id}/test`, { method: 'POST' });
      alert(result.ok ? '✅ Connection OK' : `❌ ${result.error || 'Connection failed'}`);
    } catch (e) {
      alert(`Test failed: ${e}`);
    }
  };

  const statusBadge = (status?: string) => {
    const s = status || 'stopped';
    const colors: Record<string, string> = { running: '#22c55e', starting: '#f59e0b', error: '#ef4444', stopped: '#94a3b8' };
    const labels: Record<string, string> = { running: t('channels.running'), starting: t('channels.starting'), error: t('channels.error'), stopped: t('channels.stopped') };
    return (
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12 }}>
        <span style={{ width: 8, height: 8, borderRadius: '50%', background: colors[s] || colors.stopped, display: 'inline-block' }} />
        {labels[s] || s}
      </span>
    );
  };

  const selectedPlatform = (form.platform as string) || '';
  const configFields = PLATFORM_CONFIG_FIELDS[selectedPlatform] || [];
  const isDrawerOpen = isNew || editing !== null;

  return (
    <div style={{ padding: 24, maxWidth: 900, margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 20 }}>{t('channels.title')}</h2>
          <p style={{ margin: '4px 0 0', color: '#666', fontSize: 13 }}>{t('channels.subtitle')}</p>
        </div>
        <button onClick={openNew} style={{ padding: '8px 16px', background: '#4f46e5', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 13 }}>
          + {t('channels.addChannel')}
        </button>
      </div>

      {loading ? (
        <div style={{ textAlign: 'center', padding: 40, color: '#888' }}>Loading…</div>
      ) : channels.length === 0 ? (
        <div style={{ textAlign: 'center', padding: 60, color: '#888' }}>
          <div style={{ fontSize: 40, marginBottom: 12 }}>📡</div>
          {t('channels.noChannels')}
        </div>
      ) : (
        <div style={{ display: 'grid', gap: 12 }}>
          {channels.map(ch => (
            <div key={ch.id} onClick={() => openEdit(ch)} style={{
              display: 'flex', alignItems: 'center', gap: 14, padding: '14px 18px',
              background: '#fff', border: '1px solid #e2e8f0', borderRadius: 10, cursor: 'pointer',
            }}>
              <span style={{ fontSize: 28 }}>{PLATFORM_ICONS[ch.platform] || '🔌'}</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 600, fontSize: 14 }}>{ch.name || ch.id}</div>
                <div style={{ fontSize: 12, color: '#666', marginTop: 2 }}>
                  {t(`channels.${ch.platform}`) || ch.platform} · {ch.worker_id || 'No worker'}
                </div>
              </div>
              {statusBadge(ch.status)}
              <span style={{
                padding: '2px 8px', borderRadius: 4, fontSize: 11,
                background: ch.enabled ? '#dcfce7' : '#f1f5f9',
                color: ch.enabled ? '#166534' : '#64748b',
              }}>
                {ch.enabled ? 'ON' : 'OFF'}
              </span>
            </div>
          ))}
        </div>
      )}

      {isDrawerOpen && (
        <div style={{
          position: 'fixed', top: 0, right: 0, width: 420, height: '100vh',
          background: '#fff', borderLeft: '1px solid #e2e8f0', boxShadow: '-4px 0 20px rgba(0,0,0,.1)',
          display: 'flex', flexDirection: 'column', zIndex: 1000, overflow: 'auto',
        }}>
          <div style={{ padding: '20px 24px', borderBottom: '1px solid #e2e8f0', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h3 style={{ margin: 0, fontSize: 16 }}>{isNew ? t('channels.addChannel') : (form.name as string || form.id as string)}</h3>
            <button onClick={closeDrawer} style={{ background: 'none', border: 'none', fontSize: 20, cursor: 'pointer', color: '#666' }}>✕</button>
          </div>

          <div style={{ padding: '20px 24px', flex: 1, display: 'flex', flexDirection: 'column', gap: 14 }}>
            {isNew && (
              <label style={{ fontSize: 13 }}>
                {t('channels.channelId')} *
                <input value={form.id as string || ''} onChange={e => updateForm('id', e.target.value)}
                  style={{ width: '100%', padding: '8px 10px', border: '1px solid #d1d5db', borderRadius: 6, marginTop: 4, fontSize: 13, boxSizing: 'border-box' }}
                  placeholder="my-dingtalk" />
              </label>
            )}

            {isNew && (
              <label style={{ fontSize: 13 }}>
                {t('channels.platform')} *
                <select value={selectedPlatform} onChange={e => { updateForm('platform', e.target.value); setForm(prev => ({ ...prev, config: {} })); }}
                  style={{ width: '100%', padding: '8px 10px', border: '1px solid #d1d5db', borderRadius: 6, marginTop: 4, fontSize: 13, boxSizing: 'border-box' }}>
                  <option value="">{t('channels.selectPlatform')}</option>
                  {platforms.map(p => (
                    <option key={p.id} value={p.id} disabled={!p.available}>
                      {p.name} {!p.available ? '(SDK not installed)' : ''}
                    </option>
                  ))}
                </select>
              </label>
            )}

            <label style={{ fontSize: 13 }}>
              {t('channels.name')}
              <input value={form.name as string || ''} onChange={e => updateForm('name', e.target.value)}
                style={{ width: '100%', padding: '8px 10px', border: '1px solid #d1d5db', borderRadius: 6, marginTop: 4, fontSize: 13, boxSizing: 'border-box' }} />
            </label>

            <label style={{ fontSize: 13 }}>
              {t('channels.worker')} *
              <select value={form.worker_id as string || ''} onChange={e => updateForm('worker_id', e.target.value)}
                style={{ width: '100%', padding: '8px 10px', border: '1px solid #d1d5db', borderRadius: 6, marginTop: 4, fontSize: 13, boxSizing: 'border-box' }}>
                <option value="">{t('channels.selectWorker')}</option>
                {workers.map(w => (
                  <option key={w.id} value={w.id}>{w.name} ({w.type})</option>
                ))}
              </select>
            </label>

            <label style={{ fontSize: 13, display: 'flex', alignItems: 'center', gap: 8 }}>
              <input type="checkbox" checked={!!form.enabled} onChange={e => updateForm('enabled', e.target.checked)} />
              {t('channels.enabled')}
            </label>

            {configFields.length > 0 && (
              <div style={{ borderTop: '1px solid #e2e8f0', paddingTop: 14, marginTop: 4 }}>
                <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 10 }}>
                  {t('channels.config')} — {t(`channels.${selectedPlatform}`)}
                </div>
                {configFields.map(field => (
                  <label key={field.key} style={{ fontSize: 13, display: 'block', marginBottom: 10 }}>
                    {t(field.labelKey)} {field.required && '*'}
                    {field.type === 'select' ? (
                      <select
                        value={(form.config as Record<string, unknown> || {})[field.key] as string || ''}
                        onChange={e => updateConfig(field.key, e.target.value)}
                        style={{ width: '100%', padding: '8px 10px', border: '1px solid #d1d5db', borderRadius: 6, marginTop: 4, fontSize: 13, boxSizing: 'border-box' }}
                      >
                        {field.options?.map(opt => (
                          <option key={opt.value} value={opt.value}>{t(opt.labelKey)}</option>
                        ))}
                      </select>
                    ) : (
                      <input
                        type={field.type}
                        value={(form.config as Record<string, unknown> || {})[field.key] as string || ''}
                        onChange={e => updateConfig(field.key, e.target.value)}
                        style={{ width: '100%', padding: '8px 10px', border: '1px solid #d1d5db', borderRadius: 6, marginTop: 4, fontSize: 13, boxSizing: 'border-box' }}
                      />
                    )}
                  </label>
                ))}
              </div>
            )}
          </div>

          <div style={{ padding: '16px 24px', borderTop: '1px solid #e2e8f0', display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
            {!isNew && editing && (
              <>
                <button onClick={() => handleTest(editing.id)} style={{ padding: '8px 14px', background: '#f1f5f9', border: '1px solid #d1d5db', borderRadius: 6, cursor: 'pointer', fontSize: 13 }}>
                  {t('channels.test')}
                </button>
                <button onClick={() => handleDelete(editing.id)} style={{ padding: '8px 14px', background: '#fff', border: '1px solid #fca5a5', borderRadius: 6, cursor: 'pointer', fontSize: 13, color: '#dc2626' }}>
                  {t('channels.delete')}
                </button>
              </>
            )}
            <button onClick={handleSave} disabled={saving} style={{
              padding: '8px 20px', background: '#4f46e5', color: '#fff', border: 'none',
              borderRadius: 6, cursor: saving ? 'not-allowed' : 'pointer', fontSize: 13, opacity: saving ? 0.6 : 1,
            }}>
              {saving ? '…' : t('channels.save')}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
