/**
 * Lightweight i18n engine.
 *
 * Design:
 *   - React Context provides `t(key, params?)` and `locale` / `setLocale`.
 *   - Locale bundles are static JSON (en.json, zh-CN.json).
 *   - Fallback: if a key is missing in current locale, fall back to en, then return the raw key.
 *   - Key convention: dot-path like `nav.Chat`, `settings.title`.
 *   - Params: `t('greeting', { name: 'Alice' })` replaces `{name}` in the string.
 *
 * Safety:
 *   - All existing hardcoded strings continue to work without any change.
 *   - Only components that call `t()` are affected by locale switching.
 *   - Migration can be done incrementally — one component at a time.
 */

import { createContext, useContext, useState, useCallback, useEffect, useMemo } from 'react';
import type { ReactNode } from 'react';
import type { Locale, LocaleMessages } from './types';

import enMessages from './en.json';
import zhCNMessages from './zh-CN.json';

// ── Bundles ──────────────────────────────────────────────────────────
const bundles: Record<Locale, LocaleMessages> = {
  en: enMessages as unknown as LocaleMessages,
  'zh-CN': zhCNMessages as unknown as LocaleMessages,
};

// ── Locale display info ──────────────────────────────────────────────
export const LOCALE_OPTIONS: Array<{ value: Locale; label: string; native: string }> = [
  { value: 'zh-CN', label: 'Chinese (Simplified)', native: '简体中文' },
  { value: 'en', label: 'English', native: 'English' },
];

// ── Storage key ──────────────────────────────────────────────────────
const STORAGE_KEY = 'nowork-locale';

// ── Helpers ──────────────────────────────────────────────────────────

function detectDefault(): Locale {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored && bundles[stored as Locale]) return stored as Locale;
  } catch { /* ignore */ }

  const nav = navigator.language; // e.g. 'zh-CN', 'en-US'
  if (nav.startsWith('zh')) return 'zh-CN';
  return 'en';
}

/**
 * Resolve a dot-path key from a nested object.
 * e.g. resolvePath(obj, 'nav.Chat') → 'Chat' | '聊天'
 */
function resolvePath(obj: LocaleMessages, path: string): string | undefined {
  const parts = path.split('.');
  let current: unknown = obj;
  for (const part of parts) {
    if (current == null || typeof current !== 'object') return undefined;
    current = (current as Record<string, unknown>)[part];
  }
  return typeof current === 'string' ? current : undefined;
}

/**
 * Replace `{param}` placeholders in a string.
 */
function interpolate(template: string, params?: Record<string, string | number>): string {
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (_, key) =>
    params[key] !== undefined ? String(params[key]) : `{${key}}`,
  );
}

// ── Public translate function (works outside React too) ──────────────

export function translate(locale: Locale, key: string, params?: Record<string, string | number>): string {
  const value =
    resolvePath(bundles[locale] as unknown as LocaleMessages, key) ??
    resolvePath(bundles.en as unknown as LocaleMessages, key) ??
    key;
  return interpolate(value, params);
}

// ── React Context ────────────────────────────────────────────────────

interface I18nContextValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  /** Translate a dot-path key, with optional interpolation params */
  t: (key: string, params?: Record<string, string | number>) => string;
}

const I18nContext = createContext<I18nContextValue | null>(null);

// ── Provider ─────────────────────────────────────────────────────────

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(detectDefault);

  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next);
    try { localStorage.setItem(STORAGE_KEY, next); } catch { /* ignore */ }
  }, []);

  // Keep <html lang> in sync
  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  const t = useCallback(
    (key: string, params?: Record<string, string | number>) => translate(locale, key, params),
    [locale],
  );

  const value = useMemo(() => ({ locale, setLocale, t }), [locale, setLocale, t]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

// ── Hook ─────────────────────────────────────────────────────────────

export function useI18n(): I18nContextValue {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error('useI18n must be used within <I18nProvider>');
  return ctx;
}
