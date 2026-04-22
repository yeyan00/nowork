import { useEffect, useState } from 'react';
import { useI18n } from '../i18n';

export function ReasoningPanel({ content, defaultOpen = false }: { content: string; defaultOpen?: boolean }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(defaultOpen);

  useEffect(() => {
    setOpen(defaultOpen);
  }, [defaultOpen]);

  if (!content) return null;

  return (
    <details className="collapsible-panel reasoning-panel" open={open} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary>
        <span className="panel-icon">{'\uD83D\uDCAD'}</span>
        <span className="panel-title">{t('reasoning.title')}</span>
      </summary>
      <div className="panel-content">
        <pre className="reasoning-content">{content}</pre>
      </div>
    </details>
  );
}
