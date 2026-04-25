/**
 * SettingsPage — app preferences, version info, license, update checker.
 */

import { useState, type ReactNode } from 'react';
import { useI18n, LOCALE_OPTIONS } from '../i18n';
import type { Locale } from '../i18n/types';
import { LogViewer } from './LogViewer';
import { getSessionConfig, updateSessionConfig } from '../lib/backend';

/* ── Collapsible Panel ─────────────────────────────────────────── */

function Panel({ title, defaultOpen, children }: { title: string; defaultOpen?: boolean; children: ReactNode }) {
  const [open, setOpen] = useState(defaultOpen ?? false);
  return (
    <div className="settings-section form-card" style={{ padding: '0' }}>
      <button
        type="button"
        className="panel-header"
        onClick={() => setOpen((v) => !v)}
      >
        <span className="panel-header-title">{title}</span>
        <span className={`panel-chevron ${open ? 'open' : ''}`}>▸</span>
      </button>
      {open && <div className="panel-body">{children}</div>}
    </div>
  );
}

/* ── Page ───────────────────────────────────────────────────────── */

export function SettingsPage() {
  const { t, locale, setLocale } = useI18n();
  const [updateStatus, setUpdateStatus] = useState<'idle' | 'checking' | 'upToDate' | 'available' | 'error'>('idle');
  const [latestVersion, setLatestVersion] = useState<string | null>(null);
  const [showLicense, setShowLicense] = useState(false);
  const [showLogs, setShowLogs] = useState(false);

  // Session compaction config
  const [compactionLoaded, setCompactionLoaded] = useState(false);
  const [compactionSaving, setCompactionSaving] = useState(false);
  const [compactionEnabled, setCompactionEnabled] = useState(true);
  const [compactionThreshold, setCompactionThreshold] = useState(75);
  const [compactionReserve, setCompactionReserve] = useState(4000);
  const [compactionPreserve, setCompactionPreserve] = useState(5);
  const [compactionMaxSummaries, setCompactionMaxSummaries] = useState(3);
  const [compactionDirty, setCompactionDirty] = useState(false);

  const appVersion = __APP_VERSION__;

  // Load compaction config once
  if (!compactionLoaded) {
    setCompactionLoaded(true);
    void getSessionConfig().then((cfg) => {
      const c = cfg.compaction;
      setCompactionEnabled(c.enabled);
      setCompactionThreshold(Math.round(c.context_usage_threshold * 100));
      setCompactionReserve(c.context_reserve_tokens);
      setCompactionPreserve(c.preserve_recent_messages);
      setCompactionMaxSummaries(c.max_summaries_injected);
    }).catch(() => {});
  }

  async function handleCheckUpdate() {
    setUpdateStatus('checking');
    try {
      await new Promise((r) => setTimeout(r, 800));
      setUpdateStatus('upToDate');
    } catch {
      setUpdateStatus('error');
    }
  }

  return (
    <section className="page-frame settings-page">
      <header className="page-header">
        <div>
          <h1>{t('settings.title')}</h1>
          <p>{t('settings.subtitle')}</p>
        </div>
      </header>

      <div className="settings-sections">
        {/* ── Session Compaction ─────────────────────────────── */}
        <Panel title={t('settings.session')} defaultOpen>
          <p className="settings-section-desc">{t('settings.sessionHint')}</p>

          <label className="settings-label" style={{ flexDirection: 'row', alignItems: 'center', gap: '8px' }}>
            <input type="checkbox" checked={compactionEnabled} onChange={(e) => { setCompactionEnabled(e.target.checked); setCompactionDirty(true); }} />
            <span>{t('settings.compactionEnabled')}</span>
          </label>

          {compactionEnabled && (
            <div className="settings-form" style={{ gap: '10px' }}>
              <label className="settings-label">
                {t('settings.compactionThreshold')}
                <div className="slider-row">
                  <input type="range" className="settings-slider" min={5} max={95} step={5} value={compactionThreshold} onChange={(e) => { setCompactionThreshold(Number(e.target.value)); setCompactionDirty(true); }} />
                  <span className="slider-value">{compactionThreshold}%</span>
                </div>
              </label>
              <div style={{ display: 'flex', gap: '12px' }}>
                <label className="settings-label" style={{ flex: 1 }}>
                  {t('settings.compactionReserve')}
                  <input type="number" className="settings-input" min={1000} max={50000} step={500} value={compactionReserve} onChange={(e) => { setCompactionReserve(Number(e.target.value) || 4000); setCompactionDirty(true); }} />
                </label>
                <label className="settings-label" style={{ flex: 1 }}>
                  {t('settings.compactionPreserve')}
                  <input type="number" className="settings-input" min={0} max={20} value={compactionPreserve} onChange={(e) => { setCompactionPreserve(Number(e.target.value) || 5); setCompactionDirty(true); }} />
                </label>
              </div>
              <label className="settings-label">
                {t('settings.compactionMaxSummaries')}
                <input type="number" className="settings-input" min={1} max={10} value={compactionMaxSummaries} onChange={(e) => { setCompactionMaxSummaries(Number(e.target.value) || 3); setCompactionDirty(true); }} />
              </label>
            </div>
          )}

          {compactionDirty && (
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '4px' }}>
              <button type="button" className="primary-button" disabled={compactionSaving} onClick={() => {
                setCompactionSaving(true);
                void updateSessionConfig({
                  enabled: compactionEnabled,
                  context_usage_threshold: compactionThreshold / 100,
                  context_reserve_tokens: compactionReserve,
                  preserve_recent_messages: compactionPreserve,
                  max_summaries_injected: compactionMaxSummaries,
                })
                  .then(() => { setCompactionDirty(false); })
                  .catch(() => {})
                  .finally(() => { setCompactionSaving(false); });
              }}>
                {compactionSaving ? t('settings.saving') : t('settings.save')}
              </button>
            </div>
          )}
        </Panel>

        {/* ── Language ─────────────────────────────────────── */}
        <Panel title={t('settings.language')}>
          <p className="settings-section-desc">{t('settings.languageHint')}</p>
          <div className="settings-locale-grid">
            {LOCALE_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                className={`settings-locale-card ${locale === opt.value ? 'active' : ''}`}
                onClick={() => setLocale(opt.value as Locale)}
              >
                <span className="settings-locale-label">{opt.native}</span>
                <span className="settings-locale-sub">{opt.label}</span>
              </button>
            ))}
          </div>
        </Panel>

        {/* ── Version ──────────────────────────────────────── */}
        <Panel title={t('settings.version')}>
          <div className="settings-version-row">
            <span className="settings-version-badge">v{appVersion}</span>
            <button
              type="button"
              className="soft-button"
              disabled={updateStatus === 'checking'}
              onClick={() => void handleCheckUpdate()}
            >
              {updateStatus === 'checking'
                ? t('settings.checking')
                : t('settings.checkUpdate')}
            </button>
          </div>
          {updateStatus === 'upToDate' && (
            <p className="settings-update-msg success">{t('settings.upToDate')}</p>
          )}
          {updateStatus === 'available' && (
            <p className="settings-update-msg warn">
              {t('settings.updateAvailable', { version: latestVersion ?? '?' })}
            </p>
          )}
          {updateStatus === 'error' && (
            <p className="settings-update-msg error">{t('settings.updateError')}</p>
          )}
        </Panel>

        {/* ── License ──────────────────────────────────────── */}
        <Panel title={t('settings.license')}>
          <p className="settings-section-desc">{t('settings.licenseHint')}</p>
          <button
            type="button"
            className="soft-button"
            onClick={() => setShowLicense((v) => !v)}
          >
            {showLicense ? t('common.close') : 'MIT License'}
          </button>
          {showLicense && (
            <pre className="settings-license-text">{t('settings.licenseContent')}</pre>
          )}
        </Panel>

        {/* ── Logs ──────────────────────────────────────────── */}
        <Panel title={t('logs.title')}>
          <p className="settings-section-desc">{t('logs.hint')}</p>
          <button
            type="button"
            className="soft-button"
            onClick={() => setShowLogs(true)}
          >
            {t('logs.viewLogs')}
          </button>
        </Panel>
      </div>

      {showLogs && <LogViewer onClose={() => setShowLogs(false)} />}
    </section>
  );
}
