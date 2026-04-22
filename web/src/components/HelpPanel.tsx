/**
 * HelpPanel — global help sidebar, slides in from the right.
 * Renders the bilingual user manual based on current locale.
 */

import { useMemo } from 'react';
import { useI18n } from '../i18n';
import { MarkdownContent } from './MarkdownContent';
import zhManual from '../help/zh-CN.md?raw';
import enManual from '../help/en.md?raw';

interface HelpPanelProps {
  onClose: () => void;
}

const manuals: Record<string, string> = {
  'zh-CN': zhManual,
  'en': enManual,
};

export function HelpPanel({ onClose }: HelpPanelProps) {
  const { t, locale } = useI18n();

  const content = useMemo(() => {
    return manuals[locale] || manuals['en'] || '';
  }, [locale]);

  return (
    <div className="help-overlay" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <aside className="help-sidebar">
        <div className="help-sidebar-header">
          <div className="help-sidebar-title">
            <svg viewBox="0 0 20 20" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="10" cy="10" r="8" />
              <path d="M7.5 7.5a2.5 2.5 0 0 1 5 0c0 1.5-2.5 2-2.5 3.5" />
              <line x1="10" y1="15" x2="10.01" y2="15" />
            </svg>
            <h3>{t('help.title')}</h3>
          </div>
          <button type="button" className="icon-button help-sidebar-close" onClick={onClose} aria-label="Close">
            <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><line x1="5" y1="5" x2="15" y2="15" /><line x1="15" y1="5" x2="5" y2="15" /></svg>
          </button>
        </div>
        <div className="help-sidebar-body">
          <MarkdownContent content={content} />
        </div>
      </aside>
    </div>
  );
}
