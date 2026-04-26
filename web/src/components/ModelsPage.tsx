import { useCallback, useEffect, useState } from 'react';
import { useI18n } from '../i18n';
import {
  createProvider,
  deleteProvider,
  fetchRemoteModels,
  listModels,
  setDefaultModel,
  updateProvider,
} from '../lib/backend';
import type { ProviderInfo } from '../lib/backend';

interface ModelEntry {
  localId: string;
  name: string;
  image: boolean;
  video: boolean;
  contextWindow?: number;
}

interface ProviderForm {
  id: string;
  name: string;
  type: string;
  provider: string;
  baseUrl: string;
  apiKey: string;
  models: ModelEntry[];
}

const EMPTY_FORM: ProviderForm = {
  id: '',
  name: '',
  type: 'openai_compatible',
  provider: '',
  baseUrl: '',
  apiKey: '',
  models: [],
};

function providerToForm(p: ProviderInfo): ProviderForm {
  return {
    id: p.id,
    name: p.name,
    type: p.type || 'openai_compatible',
    provider: p.provider || p.id,
    baseUrl: p.baseUrl || '',
    apiKey: p.apiKey || '',
    models: (p.models || []).map((m) => ({
      localId: m.localId || m.id.split('/').pop() || m.id,
      name: m.name,
      image: m.image || false,
      video: m.video || false,
      contextWindow: m.contextWindow || undefined,
    })),
  };
}

export function ModelsPage() {
  const { t } = useI18n();
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [form, setForm] = useState<ProviderForm>(EMPTY_FORM);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [isNew, setIsNew] = useState(false);
  const [fetching, setFetching] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [defaultModel, setDefaultModelState] = useState('');

  const reload = useCallback(async () => {
    const data = await listModels();
    setProviders(data.providers);
    setDefaultModelState(data.default_model || '');
  }, []);

  useEffect(() => {
    void reload().catch(() => {});
  }, [reload]);

  useEffect(() => {
    if (isNew) return;
    const p = providers.find((x) => x.id === selectedId);
    if (p) {
      setForm(providerToForm(p));
      setDirty(false);
    }
  }, [selectedId, providers, isNew]);

  const startNew = useCallback(() => {
    setIsNew(true);
    setSelectedId('__new__');
    setForm({ ...EMPTY_FORM });
    setDirty(false);
    setConfirmDelete(false);
  }, []);

  const cancelEdit = useCallback(() => {
    setIsNew(false);
    if (providers.length > 0) {
      setSelectedId(providers[0].id);
    } else {
      setSelectedId(null);
      setForm(EMPTY_FORM);
    }
    setDirty(false);
    setConfirmDelete(false);
  }, [providers]);

  const markDirty = useCallback(() => setDirty(true), []);

  const handleSave = useCallback(async () => {
    setSaving(true);
    try {
      if (isNew) {
        const created = await createProvider({
          id: form.id,
          name: form.name,
          type: form.type,
          provider: form.provider || form.id,
          baseUrl: form.baseUrl,
          apiKey: form.apiKey,
        });
        if (form.models.length > 0) {
          await updateProvider(created.id, { models: form.models.map((m) => ({ id: `${form.id}/${m.localId}`, ...m })) as any });
        }
        setIsNew(false);
        await reload();
        setSelectedId(form.id);
      } else {
        await updateProvider(form.id, {
          name: form.name,
          type: form.type,
          provider: form.provider,
          baseUrl: form.baseUrl,
          apiKey: form.apiKey,
          models: form.models.map((m) => ({ id: `${form.id}/${m.localId}`, ...m })) as any,
        });
        await reload();
      }
      setDirty(false);
    } finally {
      setSaving(false);
    }
  }, [isNew, form, reload]);

  const handleDelete = useCallback(async () => {
    if (!confirmDelete) {
      setConfirmDelete(true);
      return;
    }
    await deleteProvider(form.id);
    setConfirmDelete(false);
    await reload();
    if (providers.length > 1) {
      const next = providers.find((p) => p.id !== form.id);
      setSelectedId(next?.id ?? null);
    } else {
      setSelectedId(null);
      setForm(EMPTY_FORM);
    }
  }, [confirmDelete, form.id, reload, providers]);

  const handleFetchModels = useCallback(async () => {
    if (!form.baseUrl) return;
    setFetching(true);
    try {
      const remoteModels = await fetchRemoteModels(form.baseUrl, form.apiKey || undefined);
      if (remoteModels.length > 0) {
        const existing = new Set(form.models.map((m) => m.localId));
        const merged = [...form.models];
        for (const rm of remoteModels) {
          if (!existing.has(rm.id)) {
            merged.push({ localId: rm.id, name: rm.name || rm.id, image: false, video: false, contextWindow: undefined });
          }
        }
        setForm((f) => ({ ...f, models: merged }));
        setDirty(true);
      }
    } finally {
      setFetching(false);
    }
  }, [form.baseUrl, form.apiKey, form.models]);

  const updateModel = useCallback((idx: number, field: keyof ModelEntry, value: string | boolean | number | undefined) => {
    setForm((f) => {
      const models = f.models.map((m, i) => (i === idx ? { ...m, [field]: value } : m));
      return { ...f, models };
    });
    setDirty(true);
  }, []);

  const removeModel = useCallback((idx: number) => {
    setForm((f) => ({ ...f, models: f.models.filter((_, i) => i !== idx) }));
    setDirty(true);
  }, []);

  const addModel = useCallback(() => {
    setForm((f) => ({
      ...f,
      models: [...f.models, { localId: '', name: '', image: false, video: false, contextWindow: undefined }],
    }));
    setDirty(true);
  }, []);

  const handleSetDefault = useCallback(async (modelId: string) => {
    try {
      const result = await setDefaultModel(modelId);
      setDefaultModelState(result.default_model);
    } catch { /* ignore */ }
  }, []);

  return (
    <section className="page-frame">
      <header className="page-header">
        <div>
          <h1>{t('models.title')}</h1>
          <p>{t('models.subtitle')}</p>
        </div>
      </header>

      <div className="models-layout">
        <div className="models-sidebar">
          {providers.map((p) => (
            <button
              key={p.id}
              type="button"
              className={`models-sidebar-item ${p.id === selectedId && !isNew ? 'active' : ''}`}
              onClick={() => { setIsNew(false); setSelectedId(p.id); setConfirmDelete(false); }}
            >
              <strong>{p.name || p.id}</strong>
              <span className="models-sidebar-meta">
                {p.models.length} model{p.models.length !== 1 ? 's' : ''}
              </span>
            </button>
          ))}
          <button type="button" className="models-sidebar-item add" onClick={startNew}>
            + Add Provider
          </button>
        </div>

        <div className="models-editor">
          {selectedId ? (
            <>
              <div className="models-editor-header">
                <h2>{isNew ? 'New Provider' : form.name || form.id}</h2>
                {!isNew && (
                  <button
                    type="button"
                    className={`btn-delete ${confirmDelete ? 'confirm' : ''}`}
                    onClick={handleDelete}
                  >
                    {confirmDelete ? 'Confirm Delete?' : 'Delete'}
                  </button>
                )}
              </div>

              <div className="models-form">
                {isNew && (
                  <label className="settings-label">
                    Provider ID
                    <input
                      className="settings-input"
                      value={form.id}
                      onChange={(e) => { setForm((f) => ({ ...f, id: e.target.value })); markDirty(); }}
                      placeholder="my-provider"
                    />
                  </label>
                )}
                <div className="models-form-row">
                  <label className="settings-label">
                    Name
                    <input
                      className="settings-input"
                      value={form.name}
                      onChange={(e) => { setForm((f) => ({ ...f, name: e.target.value })); markDirty(); }}
                      placeholder="My Provider"
                    />
                  </label>
                  <label className="settings-label">
                    Type
                    <select
                      className="settings-select"
                      value={form.type}
                      onChange={(e) => { setForm((f) => ({ ...f, type: e.target.value })); markDirty(); }}
                    >
                      <option value="openai_compatible">{t('models.openaiCompatible')}</option>
                    </select>
                  </label>
                </div>
                <label className="settings-label">
                  Base URL
                  <input
                    className="settings-input"
                    value={form.baseUrl}
                    onChange={(e) => { setForm((f) => ({ ...f, baseUrl: e.target.value })); markDirty(); }}
                    placeholder="https://api.openai.com/v1"
                  />
                </label>
                <label className="settings-label">
                  API Key
                  <input
                    className="settings-input"
                    type="password"
                    value={form.apiKey}
                    onChange={(e) => { setForm((f) => ({ ...f, apiKey: e.target.value })); markDirty(); }}
                    placeholder="sk-..."
                  />
                </label>

                <div className="models-section-header">
                  <h3>{t('models.models')}</h3>
                  <div className="models-section-actions">
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={() => void handleFetchModels()}
                      disabled={fetching || !form.baseUrl}
                    >
                      {fetching ? 'Fetching...' : 'Fetch from API'}
                    </button>
                    <button type="button" className="btn-secondary" onClick={addModel}>
                      + Add Model
                    </button>
                  </div>
                </div>

                <div className="models-table">
                  <div className="models-table-header">
                    <span className="col-default">{t('models.default')}</span>
                    <span className="col-id">{t('models.modelId')}</span>
                    <span className="col-name">{t('models.modelName')}</span>
                    <span className="col-vision">{t('models.image')}</span>
                    <span className="col-vision">{t('models.video')}</span>
                    <span className="col-ctx">{t('models.contextWindow')}</span>
                    <span className="col-action"></span>
                  </div>
                  {form.models.map((m, idx) => {
                    const fullId = form.id && m.localId ? `${form.id}/${m.localId}` : '';
                    const isDefault = defaultModel === fullId;
                    return (
                    <div key={idx} className="models-table-row">
                      <button
                        type="button"
                        className={`default-star ${isDefault ? 'active' : ''}`}
                        title={isDefault ? 'Default model' : 'Set as default'}
                        disabled={!fullId}
                        onClick={() => { if (fullId) void handleSetDefault(fullId); }}
                      >
                        {isDefault ? '★' : '☆'}
                      </button>
                      <input
                        className="settings-input col-id"
                        value={m.localId}
                        onChange={(e) => updateModel(idx, 'localId', e.target.value)}
                        placeholder="model-id"
                      />
                      <input
                        className="settings-input col-name"
                        value={m.name}
                        onChange={(e) => updateModel(idx, 'name', e.target.value)}
                        placeholder="Model Name"
                      />
                      <label className="vision-toggle">
                        <input
                          type="checkbox"
                          checked={m.image}
                          onChange={(e) => updateModel(idx, 'image', e.target.checked)}
                        />
                        <span>{m.image ? 'Yes' : 'No'}</span>
                      </label>
                      <label className="vision-toggle">
                        <input
                          type="checkbox"
                          checked={m.video}
                          onChange={(e) => updateModel(idx, 'video', e.target.checked)}
                        />
                        <span>{m.video ? 'Yes' : 'No'}</span>
                      </label>
                      <input
                        className="settings-input col-ctx"
                        type="number"
                        value={m.contextWindow ?? ''}
                        onChange={(e) => updateModel(idx, 'contextWindow', e.target.value ? parseInt(e.target.value, 10) : undefined)}
                        placeholder="128000"
                      />
                      <button type="button" className="ws-remove" onClick={() => removeModel(idx)}>
                        ✕
                      </button>
                    </div>
                    );
                  })}
                  {form.models.length === 0 && (
                    <p className="skill-empty">{t('models.noModels')}</p>
                  )}
                </div>
              </div>

              <div className="settings-footer">
                {dirty && <span className="settings-dirty">{t('models.unsavedChanges')}</span>}
                {isNew && (
                  <button type="button" className="btn-secondary" onClick={cancelEdit}>
                    Cancel
                  </button>
                )}
                <button
                  type="button"
                  className="primary-button"
                  disabled={saving || !dirty || (isNew && !form.id)}
                  onClick={() => void handleSave()}
                >
                  {saving ? 'Saving...' : 'Save'}
                </button>
              </div>
            </>
          ) : (
            <div className="models-empty">
              <p>{t('models.selectProvider')}</p>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
