/**
 * SettingsPage — app preferences, version info, license, update checker.
 */

import { useState } from 'react';
import { useI18n, LOCALE_OPTIONS } from '../i18n';
import type { Locale } from '../i18n/types';
import { LogViewer } from './LogViewer';

export function SettingsPage() {
  const { t, locale, setLocale } = useI18n();
  const [updateStatus, setUpdateStatus] = useState<'idle' | 'checking' | 'upToDate' | 'available' | 'error'>('idle');
  const [latestVersion, setLatestVersion] = useState<string | null>(null);
  const [showLicense, setShowLicense] = useState(false);
  const [showLogs, setShowLogs] = useState(false);

  const appVersion = __APP_VERSION__;

  async function handleCheckUpdate() {
    setUpdateStatus('checking');
    try {
      // TODO: implement real GitHub release check
      // const resp = await fetch('https://api.github.com/repos/OWNER/REPO/releases/latest');
      // const data = await resp.json();
      // const remote = data.tag_name.replace(/^v/, '');
      // if (remote !== appVersion) { setLatestVersion(remote); setUpdateStatus('available'); }
      // else { setUpdateStatus('upToDate'); }
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
        {/* ── Language ─────────────────────────────────────── */}
        <div className="settings-section form-card">
          <h2 className="settings-section-title">{t('settings.language')}</h2>
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
        </div>

        {/* ── Version ──────────────────────────────────────── */}
        <div className="settings-section form-card">
          <h2 className="settings-section-title">{t('settings.version')}</h2>
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
        </div>

        {/* ── License ──────────────────────────────────────── */}
        <div className="settings-section form-card">
          <h2 className="settings-section-title">{t('settings.license')}</h2>
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
        </div>

        {/* ── Logs ──────────────────────────────────────────── */}
        <div className="settings-section form-card">
          <h2 className="settings-section-title">{t('logs.title')}</h2>
          <p className="settings-section-desc">{t('logs.hint')}</p>
          <button
            type="button"
            className="soft-button"
            onClick={() => setShowLogs(true)}
          >
            {t('logs.viewLogs')}
          </button>
        </div>
      </div>

      {showLogs && <LogViewer onClose={() => setShowLogs(false)} />}
    </section>
  );
}
