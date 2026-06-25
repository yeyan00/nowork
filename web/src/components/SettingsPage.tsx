/**
 * SettingsPage — app preferences, version info, license, update checker.
 */

import { useState } from 'react';
import type { ReactNode } from 'react';
import { useI18n, LOCALE_OPTIONS } from '../i18n';
import type { Locale } from '../i18n/types';
import { EnvSettingsSection } from './EnvSettingsSection';
import { LogViewer } from './LogViewer';
import { SessionCompactionSection } from './SessionCompactionSection';

/**
 * Open a URL in the system browser.
 * Inside Tauri (desktop shell), window.open() is blocked by WebView2,
 * so we invoke a Rust command that shells out to the OS.
 * In dev / browser mode, fall back to window.open().
 */
async function openInBrowser(url: string): Promise<void> {
  // Tauri v2 exposes __TAURI_INTERNALS__ when running inside the desktop shell
  const isTauri = !!(window as any).__TAURI_INTERNALS__;
  if (isTauri) {
    const { invoke } = await import('@tauri-apps/api/core');
    await invoke('open_external_url', { url });
  } else {
    window.open(url, '_blank', 'noopener,noreferrer');
  }
}

const RELEASES_LATEST_API = 'https://api.github.com/repos/yeyan00/nowork/releases/latest';

function normalizeVersion(version: string): string {
  return version.trim().replace(/^v/i, '');
}

function compareVersions(a: string, b: string): number {
  const pa = normalizeVersion(a).split('.').map((part) => Number.parseInt(part, 10) || 0);
  const pb = normalizeVersion(b).split('.').map((part) => Number.parseInt(part, 10) || 0);
  const len = Math.max(pa.length, pb.length);

  for (let i = 0; i < len; i += 1) {
    const av = pa[i] ?? 0;
    const bv = pb[i] ?? 0;
    if (av > bv) return 1;
    if (av < bv) return -1;
  }

  return 0;
}

/* ── Section Block ─────────────────────────────────────────────── */

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="settings-block">
      <h3 className="settings-block-title">{title}</h3>
      <div className="settings-block-body">{children}</div>
    </div>
  );
}

/* ── Page ───────────────────────────────────────────────────────── */

export function SettingsPage() {
  const { t, locale, setLocale } = useI18n();
  const [updateStatus, setUpdateStatus] = useState<'idle' | 'checking' | 'upToDate' | 'available' | 'error'>('idle');
  const [latestVersion, setLatestVersion] = useState<string | null>(null);
  const [latestReleaseUrl, setLatestReleaseUrl] = useState<string | null>(null);
  const [showLicense, setShowLicense] = useState(false);
  const [showLogs, setShowLogs] = useState(false);


  const appVersion = __APP_VERSION__;

  async function handleCheckUpdate() {
    setUpdateStatus('checking');
    setLatestVersion(null);
    setLatestReleaseUrl(null);

    try {
      const res = await fetch(RELEASES_LATEST_API, {
        headers: {
          Accept: 'application/vnd.github+json',
        },
      });

      if (!res.ok) {
        throw new Error(`Update check failed: ${res.status}`);
      }

      const data = await res.json() as { tag_name?: string; html_url?: string };
      const remoteVersion = normalizeVersion(String(data.tag_name ?? ''));
      const releaseUrl = typeof data.html_url === 'string' ? data.html_url : null;

      if (!remoteVersion) {
        throw new Error('Missing tag_name in latest release response');
      }

      setLatestVersion(remoteVersion);
      setLatestReleaseUrl(releaseUrl);

      if (compareVersions(remoteVersion, appVersion) > 0) {
        setUpdateStatus('available');
      } else {
        setUpdateStatus('upToDate');
      }
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
        <SessionCompactionSection />
        <EnvSettingsSection />

        {/* ── Language ─────────────────────────────────────── */}
        <Section title={t('settings.language')}>
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
        </Section>

        {/* ── Version & Update ──────────────────────────────── */}
        <Section title={t('settings.version')}>
          <div className="settings-version-row">
            <span className="settings-version-badge">v{appVersion}</span>
            <button
              type="button"
              className="soft-button"
              onClick={() => void openInBrowser('https://github.com/yeyan00/nowork/releases')}
            >
              {t('settings.openReleasePage')}
            </button>
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
        </Section>

        {/* ── License & Logs (inline row) ───────────────────── */}
        <Section title={t('settings.license')}>
          <div className="settings-inline-row">
            <span className="settings-section-desc" style={{ margin: 0 }}>{t('settings.licenseHint')}</span>
            <button
              type="button"
              className="soft-button"
              onClick={() => setShowLicense((v) => !v)}
            >
              {showLicense ? t('common.close') : 'MIT License'}
            </button>
          </div>
          {showLicense && (
            <pre className="settings-license-text">{t('settings.licenseContent')}</pre>
          )}
        </Section>

        <Section title={t('logs.title')}>
          <div className="settings-inline-row">
            <span className="settings-section-desc" style={{ margin: 0 }}>{t('logs.hint')}</span>
            <button
              type="button"
              className="soft-button"
              onClick={() => setShowLogs(true)}
            >
              {t('logs.viewLogs')}
            </button>
          </div>
        </Section>
      </div>

      {showLogs && <LogViewer onClose={() => setShowLogs(false)} backendAvailable={true} />}
    </section>
  );
}
