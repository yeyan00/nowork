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

export function ToolCallPanel({ tool }: { tool: ToolCall }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);

  const statusIcon = tool.error ? '\u274C' : tool.result !== null && tool.result !== undefined ? '\u2705' : '\u23F3';
  const statusClass = tool.error ? 'tool-error' : tool.result !== null && tool.result !== undefined ? 'tool-done' : 'tool-running';

  return (
    <details className={`collapsible-panel tool-panel ${statusClass}`} open={open} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary>
        <span className="panel-icon">{statusIcon}</span>
        <span className="panel-title">{tool.toolName || t('tool.unknownTool')}</span>
      </summary>
      <div className="panel-content">
        {tool.toolArgs && Object.keys(tool.toolArgs).length > 0 && (
          <div className="tool-section">
            <div className="tool-section-header">{t('tool.args')}</div>
            <pre className="tool-json"><code>{formatJson(tool.toolArgs)}</code></pre>
          </div>
        )}
        {tool.result !== null && tool.result !== undefined && (
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
    </details>
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
