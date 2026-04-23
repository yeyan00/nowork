import { useCallback, useEffect, useRef, useState } from 'react';
import { useI18n } from '../i18n';
import { fetchLogs } from '../lib/backend';
import type { LogData } from '../lib/backend';

interface LogViewerProps {
  onClose: () => void;
}

export function LogViewer({ onClose }: LogViewerProps) {
  const { t } = useI18n();
  const [data, setData] = useState<LogData | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [selectedFile, setSelectedFile] = useState('');
  const contentRef = useRef<HTMLPreElement>(null);
  const prevScrollHeight = useRef(0);

  const loadLatest = useCallback(async (file?: string) => {
    setLoading(true);
    try {
      const result = await fetchLogs(200, 0, file);
      setData(result);
      if (result.files.length > 0 && !file) {
        setSelectedFile(result.files[0]);
      }
    } catch { /* ignore */ } finally {
      setLoading(false);
    }
  }, []);

  const loadMore = useCallback(async () => {
    if (!data || !data.has_more || loadingMore) return;
    setLoadingMore(true);
    prevScrollHeight.current = contentRef.current?.scrollHeight ?? 0;
    try {
      const result = await fetchLogs(200, data.offset, selectedFile || undefined);
      setData({
        ...result,
        lines: [...result.lines, ...data.lines],
      });
    } catch { /* ignore */ } finally {
      setLoadingMore(false);
    }
  }, [data, loadingMore, selectedFile]);

  // Initial load
  useEffect(() => {
    void loadLatest();
  }, [loadLatest]);

  // After loading more, restore scroll position
  useEffect(() => {
    if (!loadingMore && contentRef.current && prevScrollHeight.current > 0) {
      const newHeight = contentRef.current.scrollHeight;
      contentRef.current.scrollTop = newHeight - prevScrollHeight.current;
      prevScrollHeight.current = 0;
    }
  }, [loadingMore, data]);

  // Scroll to top detection
  const handleScroll = useCallback(() => {
    const el = contentRef.current;
    if (!el || !data?.has_more || loadingMore) return;
    if (el.scrollTop < 40) {
      void loadMore();
    }
  }, [data, loadingMore, loadMore]);

  // ESC to close
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const lineCount = data?.lines.length ?? 0;
  const endLine = data?.total ?? 0;
  const startLine = Math.max(1, endLine - lineCount + 1);

  return (
    <div className="dialog-overlay" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="log-viewer-card">
        {/* Header */}
        <div className="log-viewer-header">
          <h2>{t('logs.title')}</h2>
          <div className="log-viewer-actions">
            {data && data.files.length > 1 && (
              <select
                className="log-file-select"
                value={selectedFile}
                onChange={(e) => { setSelectedFile(e.target.value); void loadLatest(e.target.value); }}
              >
                {data.files.map((f) => (
                  <option key={f} value={f}>{f}</option>
                ))}
              </select>
            )}
            <button
              type="button"
              className="soft-button"
              disabled={loading}
              onClick={() => void loadLatest(selectedFile || undefined)}
              title={t('logs.refresh')}
            >
              {loading ? '...' : '↻'}
            </button>
            <button type="button" className="icon-button" onClick={onClose} aria-label="Close">
              <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <line x1="5" y1="5" x2="15" y2="15" />
                <line x1="15" y1="5" x2="5" y2="15" />
              </svg>
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="log-viewer-body">
          {loading && !data ? (
            <div className="log-viewer-empty">{t('logs.loading')}</div>
          ) : !data || data.lines.length === 0 ? (
            <div className="log-viewer-empty">{t('logs.empty')}</div>
          ) : (
            <pre className="log-viewer-content" ref={contentRef} onScroll={handleScroll}>
              {loadingMore && <div className="log-loading-more">{t('logs.loadingMore')}</div>}
              {data.lines.map((line, idx) => (
                <div key={idx} className={`log-line ${getLogLevelClass(line)}`}>{line}</div>
              ))}
            </pre>
          )}
        </div>

        {/* Footer */}
        <div className="log-viewer-footer">
          {data && data.total > 0 ? (
            <span className="log-viewer-info">
              {t('logs.lineInfo', { start: startLine, end: endLine, total: data.total })}
            </span>
          ) : (
            <span />
          )}
          {loadingMore && <span className="log-viewer-loading">{t('logs.loadingMore')}</span>}
        </div>
      </div>
    </div>
  );
}

function getLogLevelClass(line: string): string {
  const upper = line.toUpperCase();
  if (upper.includes(' ERROR ') || upper.includes('CRITICAL')) return 'log-error';
  if (upper.includes(' WARNING ') || upper.includes(' WARN ')) return 'log-warn';
  if (upper.includes(' DEBUG ')) return 'log-debug';
  return '';
}
