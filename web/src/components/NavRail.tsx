import { useI18n } from '../i18n';
import type { AppPage } from '../types';

const pages: Array<{ page: AppPage; icon: string; i18nKey: string }> = [
  { page: 'Chat', icon: 'C', i18nKey: 'nav.Chat' },
  { page: 'Workers', icon: 'W', i18nKey: 'nav.Workers' },
  { page: 'Schedules', icon: 'Q', i18nKey: 'nav.Schedules' },
  { page: 'Skills', icon: 'S', i18nKey: 'nav.Skills' },
  { page: 'Knowledge', icon: 'K', i18nKey: 'nav.Knowledge' },
  { page: 'MCP', icon: 'M', i18nKey: 'nav.MCP' },
  { page: 'Models', icon: 'L', i18nKey: 'nav.Models' },
  { page: 'Settings', icon: 'T', i18nKey: 'nav.Settings' }
];

interface NavRailProps {
  activePage: AppPage;
  onChange: (page: AppPage) => void;
  onHelp: () => void;
}

export function NavRail({ activePage, onChange, onHelp }: NavRailProps) {
  const { t } = useI18n();

  return (
    <aside className="nav-rail">
      <div className="brand-block">
        <div className="brand-mark">N</div>
        <div className="brand-mini">NW</div>
      </div>

      <nav className="nav-list">
        {pages.map(({ page, icon, i18nKey }) => (
          <button
            key={page}
            type="button"
            className={page === activePage ? 'nav-item active' : 'nav-item'}
            onClick={() => onChange(page)}
            title={t(i18nKey)}
          >
            <span className="nav-icon" aria-hidden="true">
              {icon}
            </span>
            <span className="nav-label">{t(i18nKey)}</span>
          </button>
        ))}
      </nav>

      <div className="nav-rail-bottom">
        <button
          type="button"
          className="nav-item nav-help-btn"
          onClick={onHelp}
          title={t('nav.Help')}
        >
          <span className="nav-icon" aria-hidden="true">
            <svg viewBox="0 0 20 20" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="10" cy="10" r="8" />
              <path d="M7.5 7.5a2.5 2.5 0 0 1 5 0c0 1.5-2.5 2-2.5 3.5" />
              <line x1="10" y1="15" x2="10.01" y2="15" />
            </svg>
          </span>
          <span className="nav-label">{t('nav.Help')}</span>
        </button>
      </div>
    </aside>
  );
}
