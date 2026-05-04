import { useCallback, useEffect, useState } from 'react';
import { useI18n } from '../i18n';
import { readFile, readRawFile, getFileCategory, getRelativePath, type FileCategory } from '../lib/filePreview';
import { MarkdownContent } from './MarkdownContent';
import type { PreviewingFile, WorkspaceInfo } from '../types';

interface PreviewPanelProps {
  file: PreviewingFile | null;
  workspace: WorkspaceInfo | null;
  onClose: () => void;
}

/**
 * Renders a preview of the selected file based on its category.
 */
export function PreviewPanel({ file, workspace, onClose }: PreviewPanelProps) {
  const { t } = useI18n();
  const [content, setContent] = useState('');
  const [imageSrc, setImageSrc] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<'preview' | 'edit'>('preview');

  // Load file content when previewingFile changes
  useEffect(() => {
    if (!file) {
      setContent('');
      setImageSrc('');
      setError(null);
      setLoading(false);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);

    const category = file.category;

    if (category === 'image') {
      // Load image via raw API
      void readRawFile(file.path)
        .then(result => {
          if (!cancelled) {
            setImageSrc(result.dataUrl);
            setContent('');
            setLoading(false);
          }
        })
        .catch(e => {
          if (!cancelled) {
            setError(e instanceof Error ? e.message : 'Failed to load image');
            setLoading(false);
          }
        });
    } else if (file.content && file.source === 'message') {
      // Content already available from tool call
      if (!cancelled) {
        setContent(file.content);
        setImageSrc('');
        setLoading(false);
      }
    } else {
      // Load from backend
      void readFile(file.path)
        .then(result => {
          if (!cancelled) {
            setContent(result.content);
            setImageSrc('');
            setLoading(false);
          }
        })
        .catch(e => {
          if (!cancelled) {
            setError(e instanceof Error ? e.message : 'Failed to read file');
            setLoading(false);
          }
        });
    }

    // Reset view mode per file
    setViewMode(category === 'code' || category === 'style' ? 'edit' : 'preview');

    return () => {
      cancelled = true;
    };
  }, [file?.path, file?.category, file?.content, file?.source]);

  const handleCopy = useCallback(async () => {
    if (!content) return;
    try {
      await navigator.clipboard.writeText(content);
    } catch {
      // Fallback: do nothing
    }
  }, [content]);

  // Empty state
  if (!file) {
    return (
      <div className="preview-panel preview-panel-empty">
        <div className="preview-empty-icon">📄</div>
        <div className="preview-empty-text">
          {t('filePreview.selectToPreview') || 'Select a file to preview'}
        </div>
        <div className="preview-empty-hint">
          {t('filePreview.clickFileHint') || 'Click a file in the tree or a file card in chat'}
        </div>
      </div>
    );
  }

  const category = file.category;
  const relativePath = workspace ? getRelativePath(file.path, workspace.path) : file.path;

  const canToggleView = category === 'markdown' || category === 'json' || category === 'html';

  return (
    <div className="preview-panel">
      {/* Header */}
      <div className="preview-header">
        <span className="preview-file-icon">{getCategoryEmoji(category)}</span>
        <span className="preview-file-name" title={file.path}>{file.name}</span>
        <span className="preview-file-path" title={file.path}>{relativePath}</span>

        <div className="preview-header-actions">
          {canToggleView && (
            <button
              type="button"
              className="preview-mode-btn"
              onClick={() => setViewMode(v => v === 'preview' ? 'edit' : 'preview')}
              title={viewMode === 'preview' ? (t('filePreview.switchToEdit') || 'Edit') : (t('filePreview.switchToPreview') || 'Preview')}
            >
              {viewMode === 'preview' ? '✏️' : '👁️'}
            </button>
          )}
          {content && (
            <button type="button" className="preview-action-btn" onClick={handleCopy} title="Copy content">
              📋
            </button>
          )}
          <button type="button" className="preview-action-btn" onClick={onClose} title="Close preview">
            ✕
          </button>
        </div>
      </div>

      {/* Loading */}
      {loading && (
        <div className="preview-loading">
          <span className="preview-spinner" /> {t('filePreview.loading') || 'Loading…'}
        </div>
      )}

      {/* Error */}
      {error && <div className="preview-error">{error}</div>}

      {/* Content */}
      {!loading && !error && (
        <div className="preview-content">
          {/* Image */}
          {category === 'image' && imageSrc && (
            <div className="preview-image-wrap">
              <img src={imageSrc} alt={file.name} className="preview-image" />
            </div>
          )}

          {/* Markdown preview */}
          {category === 'markdown' && viewMode === 'preview' && content && (
            <div className="preview-markdown">
              <MarkdownContent content={content} />
            </div>
          )}

          {/* JSON preview */}
          {category === 'json' && viewMode === 'preview' && content && (
            <JsonPreview content={content} />
          )}

          {/* HTML preview */}
          {category === 'html' && viewMode === 'preview' && content && (
            <iframe
              srcDoc={content}
              className="preview-html-iframe"
              sandbox="allow-scripts allow-same-origin allow-forms"
              title="HTML Preview"
            />
          )}

          {/* Text/code view (edit mode for md/json/html, or any code/style file) */}
          {((category === 'code' || category === 'style') || (viewMode === 'edit' && content)) && (
            <pre className="preview-code"><code>{content}</code></pre>
          )}
        </div>
      )}

      {/* Source label */}
      {file.source === 'message' && (
        <div className="preview-source-label">
          {t('filePreview.fromMessage') || 'From chat message'}
        </div>
      )}
    </div>
  );
}

// ── JSON Preview Component ────────────────────────────────────

function JsonPreview({ content }: { content: string }) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  let parsed: unknown;
  try {
    parsed = JSON.parse(content);
  } catch {
    return <pre className="preview-code"><code>{content}</code></pre>;
  }

  const toggle = (path: string) => {
    setCollapsed(prev => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  return (
    <div className="preview-json">
      <JsonNode value={parsed} path="$" collapsed={collapsed} onToggle={toggle} depth={0} />
    </div>
  );
}

function JsonNode({ value, path, collapsed, onToggle, depth }: {
  value: unknown;
  path: string;
  collapsed: Set<string>;
  onToggle: (path: string) => void;
  depth: number;
}) {
  if (value === null) return <span className="json-null">null</span>;
  if (typeof value === 'boolean') return <span className="json-bool">{String(value)}</span>;
  if (typeof value === 'number') return <span className="json-number">{value}</span>;
  if (typeof value === 'string') return <span className="json-string">"{value}"</span>;

  const isCollapsed = collapsed.has(path);
  const isArr = Array.isArray(value);
  const entries = isArr ? value.map((v, i) => [String(i), v] as const) : Object.entries(value as Record<string, unknown>);
  const open = isArr ? '[' : '{';
  const close = isArr ? ']' : '}';

  if (isCollapsed) {
    return (
      <span className="json-collapsible" onClick={() => onToggle(path)} style={{ cursor: 'pointer' }}>
        {open}…{close}
        <span className="json-summary"> {entries.length} items</span>
      </span>
    );
  }

  if (depth > 6) {
    return <span>{open}…{close}</span>;
  }

  return (
    <span>
      {open}
      <ul className="json-children" style={{ paddingLeft: `${12 + depth * 12}px` }}>
        {entries.map(([key, val]) => (
          <li key={key} className="json-entry">
            {!isArr && <span className="json-key">"{key}": </span>}
            <JsonNode value={val} path={`${path}.${key}`} collapsed={collapsed} onToggle={onToggle} depth={depth + 1} />
            {(val !== null && typeof val === 'object') && (
              <span className="json-toggle" onClick={() => onToggle(`${path}.${key}`)} title="Toggle">
                {collapsed.has(`${path}.${key}`) ? ' ▸' : ' ▾'}
              </span>
            )}
          </li>
        ))}
      </ul>
      {close}
    </span>
  );
}

// ── Helpers ────────────────────────────────────────────────────

function getCategoryEmoji(category: FileCategory): string {
  switch (category) {
    case 'image': return '🖼️';
    case 'markdown': return '📝';
    case 'json': return '📋';
    case 'html': return '🌐';
    case 'style': return '🎨';
    case 'code': return '📄';
    default: return '📄';
  }
}
