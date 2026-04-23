import { useCallback, useEffect, useRef, useState } from 'react';
import { useI18n } from '../i18n';

export function ReasoningPanel({ content, defaultOpen = false }: { content: string; defaultOpen?: boolean }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(defaultOpen);
  const contentRef = useRef<HTMLPreElement>(null);
  const isUserAtBottom = useRef(true);

  useEffect(() => {
    setOpen(defaultOpen);
  }, [defaultOpen]);

  const handleScroll = useCallback(() => {
    const el = contentRef.current;
    if (!el) return;
    isUserAtBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
  }, []);

  useEffect(() => {
    if (!open || !isUserAtBottom.current) return;
    requestAnimationFrame(() => {
      if (!contentRef.current || !isUserAtBottom.current) return;
      contentRef.current.scrollTop = contentRef.current.scrollHeight;
    });
  }, [content, open]);

  if (!content) return null;

  return (
    <details className="collapsible-panel reasoning-panel" open={open} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary>
        <span className="panel-icon">{'\uD83D\uDCAD'}</span>
        <span className="panel-title">{t('reasoning.title')}</span>
      </summary>
      <div className="panel-content">
        <pre ref={contentRef} className="reasoning-content" onScroll={handleScroll}>{content}</pre>
      </div>
    </details>
  );
}
