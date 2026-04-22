import { useCallback, useEffect, useState } from 'react';
import { useI18n } from '../i18n';
import {
  createKnowledgeBase,
  deleteKnowledgeBase,
  listKnowledgeBases,
  reloadKnowledgeBase,
  updateKnowledgeBase,
} from '../lib/backend';
import type { KnowledgeBase } from '../lib/backend';

export function KnowledgePage() {
  const { t } = useI18n();
  const [items, setItems] = useState<KnowledgeBase[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [paths, setPaths] = useState('');
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState('');
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [embedderType, setEmbedderType] = useState('openai');

  const load = useCallback(() => {
    setLoading(true);
    void listKnowledgeBases()
      .then((kbs) => {
        setItems(kbs);
        if (kbs.length > 0 && !selectedId) setSelectedId(kbs[0].id);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [selectedId]);

  useEffect(() => { load(); }, []);

  const selected = items.find((kb) => kb.id === selectedId) ?? null;

  useEffect(() => {
    if (!selected) return;
    setName(selected.name);
    setDescription(selected.description);
    setPaths((selected.paths ?? []).join('\n'));
    setEmbedderType(((selected.embedder ?? {}) as Record<string, unknown>).type as string || 'openai');
    setDirty(false);
  }, [selectedId, items]);

  const markDirty = useCallback(() => setDirty(true), []);

  const handleSave = useCallback(() => {
    if (!selectedId) return;
    setSaving(true);
    void updateKnowledgeBase(selectedId, {
      name,
      description,
      config: {
        paths: paths.split('\n').map((p) => p.trim()).filter(Boolean),
        embedder: { type: embedderType },
      },
    }).then((updated) => {
      setItems((prev) => prev.map((kb) => (kb.id === selectedId ? updated : kb)));
      setDirty(false);
    }).catch(() => {}).finally(() => setSaving(false));
  }, [selectedId, name, description, paths, embedderType]);

  const handleCreate = useCallback(() => {
    if (!newName.trim()) return;
    void createKnowledgeBase({ name: newName.trim() }).then((kb) => {
      setItems((prev) => [...prev, kb]);
      setSelectedId(kb.id);
      setShowCreate(false);
      setNewName('');
    }).catch(() => {});
  }, [newName]);

  const handleDelete = useCallback((id: string) => {
    void deleteKnowledgeBase(id).then(() => {
      setItems((prev) => prev.filter((kb) => kb.id !== id));
      if (selectedId === id) setSelectedId(items[0]?.id ?? null);
      setDeleteTarget(null);
    }).catch(() => {});
  }, [selectedId, items]);

  const handleReload = useCallback((id: string) => {
    void reloadKnowledgeBase(id).catch(() => {});
  }, []);

  if (loading) return <section className="page-frame"><p>{t('knowledge.loading')}</p></section>;

  return (
    <section className="page-frame">
      <div className="page-header">
        <div>
          <h1>{t('knowledge.title')}</h1>
          <p>{t('knowledge.subtitle')}</p>
        </div>
        <div className="header-actions-right">
          <span className="token-pill">{items.length} bases</span>
          <button type="button" className="primary-button" onClick={() => setShowCreate(true)}>
            + Create
          </button>
        </div>
      </div>

      <div className="knowledge-layout">
        <div className="knowledge-sidebar">
          {items.map((kb) => (
            <div key={kb.id} className={`knowledge-item ${selectedId === kb.id ? 'active' : ''}`}>
              <button type="button" className="knowledge-item-btn" onClick={() => setSelectedId(kb.id)}>
                <span className="knowledge-item-name">{kb.name || kb.id}</span>
                <span className="knowledge-item-meta">{(kb.paths ?? []).length} paths</span>
              </button>
              <button
                type="button"
                className={`knowledge-item-del ${deleteTarget === kb.id ? 'confirm' : ''}`}
                onClick={(e) => {
                  e.stopPropagation();
                  if (deleteTarget === kb.id) {
                    void handleDelete(kb.id);
                  } else {
                    setDeleteTarget(kb.id);
                  }
                }}
                onBlur={() => setDeleteTarget(null)}
              >
                {deleteTarget === kb.id ? 'Del?' : 'x'}
              </button>
            </div>
          ))}
          {items.length === 0 && <p className="knowledge-empty">{t('knowledge.empty')}</p>}
        </div>

        {selected && (
          <div className="knowledge-detail">
            <div className="settings-section">
              <h3 className="settings-section-title">{t('knowledge.name')}</h3>
              <input
                className="settings-input"
                value={name}
                onChange={(e) => { setName(e.target.value); markDirty(); }}
              />

              <h3 className="settings-section-title" style={{ marginTop: '1rem' }}>{t('knowledge.description')}</h3>
              <textarea
                className="settings-textarea"
                rows={3}
                value={description}
                onChange={(e) => { setDescription(e.target.value); markDirty(); }}
              />

              <h3 className="settings-section-title" style={{ marginTop: '1rem' }}>{t('knowledge.paths')}</h3>
              <textarea
                className="settings-textarea"
                rows={6}
                value={paths}
                onChange={(e) => { setPaths(e.target.value); markDirty(); }}
                placeholder={'C:/docs/api\nC:/docs/guides\n./README.md'}
              />

              <h3 className="settings-section-title" style={{ marginTop: '1rem' }}>{t('knowledge.embedder')}</h3>
              <div className="settings-form">
                <label className="settings-label" style={{ flexDirection: 'row', alignItems: 'center', gap: '6px' }}>
                  <input
                    type="radio"
                    name="embedder-type"
                    value="openai"
                    checked={embedderType === 'openai'}
                    onChange={() => { setEmbedderType('openai'); markDirty(); }}
                  />
                  <span>{t('knowledge.openaiApi')}</span>
                </label>
                <label className="settings-label" style={{ flexDirection: 'row', alignItems: 'center', gap: '6px' }}>
                  <input
                    type="radio"
                    name="embedder-type"
                    value="sentence-transformer"
                    checked={embedderType === 'sentence-transformer'}
                    onChange={() => { setEmbedderType('sentence-transformer'); markDirty(); }}
                  />
                  <span>{t('knowledge.sentenceTransformer')}</span>
                </label>
              </div>
            </div>

            <div className="settings-footer" style={{ borderTop: '1px solid rgba(132,146,170,0.1)', marginTop: '1rem' }}>
              {dirty && <span className="settings-dirty">{t('knowledge.unsavedChanges')}</span>}
              <button
                type="button"
                className="secondary-button"
                onClick={() => handleReload(selected.id)}
              >
                Reload
              </button>
              <button
                type="button"
                className="primary-button"
                disabled={saving || !dirty}
                onClick={handleSave}
              >
                {saving ? 'Saving...' : 'Save'}
              </button>
            </div>
          </div>
        )}
      </div>

      {showCreate && (
        <div className="dialog-overlay" onClick={() => setShowCreate(false)}>
          <div className="dialog-card" onClick={(e) => e.stopPropagation()}>
            <div className="dialog-header">
              <h2>{t('knowledge.createTitle')}</h2>
              <button type="button" className="icon-button" onClick={() => setShowCreate(false)}>X</button>
            </div>
            <input
              type="text"
              className="dialog-input"
              placeholder="Knowledge base name"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') void handleCreate(); }}
            />
            <div className="dialog-actions">
              <button type="button" className="secondary-button" onClick={() => setShowCreate(false)}>{t('knowledge.cancel')}</button>
              <button
                type="button"
                className="primary-button"
                disabled={!newName.trim()}
                onClick={() => void handleCreate()}
              >
                Create
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
