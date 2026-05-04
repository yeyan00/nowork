import { useState, useCallback, useMemo } from 'react';
import { useI18n } from '../i18n';
import { getFileCategory, getPreviewSnippet, getFileName, getRelativePath } from '../lib/filePreview';
import type { PreviewingFile, ToolCall } from '../types';

interface FileCardProps {
  toolCall: ToolCall;
  workspacePath: string | null;
  onPreview: (file: PreviewingFile) => void;
  messageId?: string;
}

/**
 * A compact card shown in chat messages when a worker writes a file.
 * Displays file name, path, a snippet preview, and a [Preview] button.
 */
export function FileCard({ toolCall, workspacePath, onPreview, messageId }: FileCardProps) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState(false);

  const filePath = String(toolCall.toolArgs?.path ?? toolCall.toolArgs?.file_path ?? toolCall.toolArgs?.filePath ?? '');
  const content = typeof toolCall.toolArgs?.content === 'string'
    ? toolCall.toolArgs.content
    : typeof toolCall.toolArgs?.contents === 'string'
      ? toolCall.toolArgs.contents
      : typeof toolCall.result === 'string'
        ? toolCall.result
        : '';

  const fileName = getFileName(filePath);
  const category = getFileCategory(filePath);
  const hasError = !!toolCall.error;
  const relativePath = workspacePath ? getRelativePath(filePath, workspacePath) : filePath;

  const handlePreview = useCallback(() => {
    onPreview({
      workspacePath: workspacePath || '',
      path: filePath,
      name: fileName,
      extension: filePath.split('.').pop()?.toLowerCase(),
      content,
      category,
      source: 'message',
      toolCallId: toolCall.toolCallId,
      messageId,
    });
  }, [category, content, fileName, filePath, messageId, onPreview, toolCall.toolCallId, workspacePath]);

  const snippet = getPreviewSnippet(content, 5, 100);

  return (
    <div className={`file-card ${hasError ? 'file-card-error' : ''}`}>
      <div className="file-card-header" onClick={() => setExpanded(v => !v)}>
        <span className="file-card-icon">{getCategoryEmoji(category)}</span>
        <span className="file-card-name">{fileName}</span>
        <span className="file-card-path">{relativePath}</span>
        {hasError && <span className="file-card-error-badge">❌</span>}
        {!hasError && toolCall.result !== null && <span className="file-card-success-badge">✅</span>}
        <span className="file-card-toggle">{expanded ? '▾' : '▸'}</span>
      </div>

      {expanded && snippet && (
        <div className="file-card-snippet">
          <pre><code>{snippet}</code></pre>
        </div>
      )}

      <div className="file-card-actions">
        <button
          type="button"
          className="file-card-preview-btn"
          onClick={handlePreview}
          disabled={hasError}
        >
          👁️ {t('filePreview.preview') || 'Preview'}
        </button>
        <button
          type="button"
          className="file-card-copy-path-btn"
          onClick={() => void navigator.clipboard.writeText(filePath).catch(() => {})}
          title={filePath}
        >
          📋
        </button>
      </div>
    </div>
  );
}

/**
 * Check if a tool call is a file write operation.
 */
export function isWriteFileToolCall(toolCall: ToolCall): boolean {
  const name = toolCall.toolName.toLowerCase();
  return name === 'write_file' || name === 'write';
}

function getCategoryEmoji(category: string): string {
  switch (category) {
    case 'image': return '🖼️';
    case 'markdown': return '📝';
    case 'json': return '📋';
    case 'html': return '🌐';
    case 'style': return '🎨';
    default: return '📄';
  }
}
