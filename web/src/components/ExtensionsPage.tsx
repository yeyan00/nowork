import { useCallback, useEffect, useState } from 'react';
import { useI18n } from '../i18n';
import { installExtension, listExtensions, uninstallExtension } from '../lib/backend';
import type { ExtensionInfo } from '../lib/backend';

export function ExtensionsPage() {
  const { t } = useI18n();
  const [extensions, setExtensions] = useState<ExtensionInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [installing, setInstalling] = useState<string | null>(null);
  const [message, setMessage] = useState<{ id: string; text: string; ok: boolean } | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    void listExtensions()
      .then(setExtensions)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, []);

  const handleInstall = useCallback((ext: ExtensionInfo) => {
    setInstalling(ext.id);
    setMessage(null);
    void installExtension(ext.id)
      .then((result) => {
        if (result.ok) {
          setMessage({ id: ext.id, text: t('extensions.installedOk'), ok: true });
          load();
        } else {
          setMessage({ id: ext.id, text: result.error || t('extensions.installFailed'), ok: false });
        }
      })
      .catch((e: Error) => {
        setMessage({ id: ext.id, text: e.message, ok: false });
      })
      .finally(() => setInstalling(null));
  }, [load]);

  const handleUninstall = useCallback((ext: ExtensionInfo) => {
    setInstalling(ext.id);
    setMessage(null);
    void uninstallExtension(ext.id)
      .then((result) => {
        if (result.ok) {
          setMessage({ id: ext.id, text: t('extensions.uninstalled'), ok: true });
          load();
        } else {
          setMessage({ id: ext.id, text: result.error || t('extensions.uninstallFailed'), ok: false });
        }
      })
      .catch((e: Error) => {
        setMessage({ id: ext.id, text: e.message, ok: false });
      })
      .finally(() => setInstalling(null));
  }, [load]);

  if (loading) return <section className="page-frame"><p>{t('extensions.loading')}</p></section>;

  const categories = [...new Set(extensions.map((e) => e.category))];

  return (
    <section className="page-frame">
      <div className="page-header">
        <div>
          <h1>{t('extensions.title')}</h1>
          <p>{t('extensions.subtitle')}</p>
        </div>
        <div className="header-actions-right">
          <span className="token-pill">
            {extensions.filter((e) => e.status === 'installed').length}/{extensions.length} installed
          </span>
        </div>
      </div>

      {categories.map((cat) => (
        <div key={cat} style={{ marginBottom: '1.5rem' }}>
          <h3 style={{ fontSize: '13px', color: '#6b7a94', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '8px' }}>
            {cat === 'embedding' ? t('extensions.embeddingModels') : cat === 'vector_db' ? t('extensions.vectorDatabases') : cat}
          </h3>
          <div className="card-grid">
            {extensions.filter((e) => e.category === cat).map((ext) => (
              <article key={ext.id} className="info-card" style={{ position: 'relative' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  <strong style={{ fontSize: '14px' }}>{ext.name}</strong>
                  <span
                    style={{
                      fontSize: '11px',
                      padding: '2px 8px',
                      borderRadius: '10px',
                      background: ext.status === 'installed' ? '#e8f5e9' : '#f5f5f5',
                      color: ext.status === 'installed' ? '#2e7d32' : '#999',
                    }}
                  >
                    {ext.status === 'installed' ? `v${ext.version || 'ok'}` : ext.install_size}
                  </span>
                </div>
                <p style={{ fontSize: '12px', color: '#666', margin: '6px 0', lineHeight: '1.5' }}>{ext.description}</p>
                <div style={{ fontSize: '11px', color: '#999', marginBottom: '8px' }}>
                  pip install {ext.pip_packages.join(' ')}
                </div>
                <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
                  {ext.status === 'installed' ? (
                    <button
                      type="button"
                      className="secondary-button"
                      style={{ padding: '4px 12px', fontSize: '12px' }}
                      disabled={installing === ext.id}
                      onClick={() => handleUninstall(ext)}
                    >
                      {installing === ext.id ? '...' : t('extensions.uninstall')}
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="primary-button"
                      style={{ padding: '4px 12px', fontSize: '12px' }}
                      disabled={installing === ext.id}
                      onClick={() => handleInstall(ext)}
                    >
                      {installing === ext.id ? t('extensions.installing') : `Install (${ext.install_size})`}
                    </button>
                  )}
                  {message?.id === ext.id && (
                    <span style={{ fontSize: '11px', color: message.ok ? '#2e7d32' : '#d32f2f' }}>
                      {message.text}
                    </span>
                  )}
                </div>
              </article>
            ))}
          </div>
        </div>
      ))}
    </section>
  );
}
