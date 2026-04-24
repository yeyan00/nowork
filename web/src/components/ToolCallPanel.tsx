import { useState } from 'react';
import { useI18n } from '../i18n';
import type { ToolCall } from '../types';

function formatJson(obj: unknown): string {
  if (obj === null || obj === undefined) return '';
  if (typeof obj === 'string') {
    try {
      return JSON.stringify(JSON.parse(obj), null, 2);
    } catch {
      return obj;
    }
  }
  return JSON.stringify(obj, null, 2);
}

function shortPath(p: string): string {
  if (!p) return '';
  const normalized = p.replace(/\\/g, '/');
  const segments = normalized.split('/').filter(Boolean);
  return segments.length <= 2 ? normalized : segments.slice(-2).join('/');
}

function shortVal(v: unknown): string {
  const s = String(v ?? '');
  return s.length > 25 ? s.substring(0, 22) + '…' : s;
}

function formatToolSummary(toolName: string, args: Record<string, unknown>): string {
  // Support both camelCase and snake_case arg names from different sources
  const getPath = () => String(args.path ?? args.file_path ?? args.filePath ?? '');
  switch (toolName) {
    case 'read_file':
    case 'read': {
      const path = shortPath(getPath());
      const offset = args.offset != null ? `:${args.offset}` : '';
      const limit = args.limit != null ? `-${Number(args.offset || 0) + Number(args.limit)}` : '';
      return path ? `${path}${offset}${limit || ''}` : toolName;
    }
    case 'edit_file':
    case 'edit': {
      const path = shortPath(getPath());
      const oldText = String(args.oldText ?? args.old_text ?? '');
      const preview = oldText.split('\n')[0]?.trim().substring(0, 35) || '';
      return preview ? `${path} — ${preview}${oldText.length > 35 ? '…' : ''}` : (path || toolName);
    }
    case 'write_file':
    case 'write': {
      const path = shortPath(getPath());
      const contentLen = String(args.content ?? args.contents ?? '').length;
      return path ? `${path} (${contentLen.toLocaleString()} chars)` : toolName;
    }
    case 'run_shell':
    case 'shell':
    case 'bash':
    case 'execute_shell': {
      const cmd = String(args.command ?? args.cmd ?? '').split('\n')[0] ?? '';
      return cmd ? (cmd.length > 60 ? cmd.substring(0, 57) + '…' : cmd) : toolName;
    }
    case 'grep':
    case 'search': {
      const pattern = String(args.pattern ?? args.query ?? args.search_string ?? '');
      const path = shortPath(String(args.path ?? args.file_path ?? '.'));
      return pattern ? `/${pattern}/ in ${path}` : toolName;
    }
    case 'find':
    case 'list_dir':
    case 'ls': {
      const path = shortPath(String(args.path ?? args.directory ?? '.'));
      const name = args.name ? ` "${args.name}"` : '';
      return `${path}${name}`;
    }
    default: {
      // Generic: show tool_name + key args (skip large text fields)
      const skipKeys = new Set(['content', 'contents', 'oldText', 'old_text', 'newText', 'new_text']);
      const entries = Object.entries(args)
        .filter(([k]) => !skipKeys.has(k))
        .slice(0, 3);
      const suffix = entries.length ? ' ' + entries.map(([k, v]) => `${k}=${shortVal(v)}`).join(' ') : '';
      return `${toolName}${suffix}`;
    }
  }
}

export function ToolCallPanel({ tool }: { tool: ToolCall }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);

  const summary = formatToolSummary(tool.toolName, tool.toolArgs || {});
  const hasArgs = tool.toolArgs && Object.keys(tool.toolArgs).length > 0;
  const hasResult = tool.result !== null && tool.result !== undefined;
  const statusIcon = tool.error ? '❌' : hasResult ? '✅' : '⏳';
  const statusClass = tool.error ? 'error' : hasResult ? 'done' : 'running';

  return (
    <div className={`tool-chip ${statusClass}`}>
      <button type="button" className="tool-chip-header" onClick={() => setOpen(!open)}>
        <span className="tool-chip-status">{statusIcon}</span>
        <span className="tool-chip-summary">{summary}</span>
        <span className="tool-chip-toggle">{open ? '▾' : '▸'}</span>
      </button>

      {open && (
        <div className="tool-chip-detail">
          {hasArgs && (
            <div className="tool-section">
              <div className="tool-section-header">{t('tool.args')}</div>
              <pre className="tool-json"><code>{formatJson(tool.toolArgs)}</code></pre>
            </div>
          )}
          {hasResult && (
            <div className="tool-section">
              <div className="tool-section-header">{t('tool.result')}</div>
              <pre className="tool-json"><code>{formatJson(tool.result)}</code></pre>
            </div>
          )}
          {tool.error && (
            <div className="tool-section tool-error-section">
              <div className="tool-section-header">{t('tool.error')}</div>
              <pre className="tool-error-text">{String(tool.error)}</pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function ToolCallList({ tools }: { tools: ToolCall[] }) {
  if (!tools || tools.length === 0) return null;
  return (
    <div className="tool-call-list">
      {tools.map((tool, index) => (
        <ToolCallPanel key={tool.toolCallId || `${tool.toolName}-${index}`} tool={tool} />
      ))}
    </div>
  );
}
