import { useCallback, useEffect, useState } from 'react';
import { useI18n } from '../i18n';
import { listMCPServers, saveMCPServers, testMCPConnection } from '../lib/backend';
import type { MCPServer, MCPToolConfig } from '../lib/backend';

type Transport = 'stdio' | 'sse' | 'streamable-http';
type McpTab = 'config' | 'tools';

interface ServerForm {
  name: string;
  transport: Transport;
  command: string;
  url: string;
  envText: string;
  timeout_seconds: number;
  tools: MCPToolConfig[];
  verified: boolean;
}

const EMPTY: ServerForm = {
  name: '',
  transport: 'stdio',
  command: '',
  url: '',
  envText: '',
  timeout_seconds: 10,
  tools: [],
  verified: false,
};

export function MCPPage() {
  const { t } = useI18n();
  const [servers, setServers] = useState<MCPServer[]>([]);
  const [form, setForm] = useState<ServerForm>(EMPTY);
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [isNew, setIsNew] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testError, setTestError] = useState('');
  const [mcpTab, setMcpTab] = useState<McpTab>('config');

  const reload = useCallback(async () => {
    const data = await listMCPServers();
    setServers(data);
  }, []);

  useEffect(() => {
    void reload().catch(() => {});
  }, [reload]);

  useEffect(() => {
    if (isNew) return;
    if (selectedIdx === null || selectedIdx >= servers.length) {
      setForm(EMPTY);
      return;
    }
    const s = servers[selectedIdx];
    const envPairs = Object.entries(s.env ?? {}).map(([k, v]) => `${k}=${v}`).join('\n');
    setForm({
      name: s.name,
      transport: s.transport as Transport,
      command: s.command ?? '',
      url: s.url ?? '',
      envText: envPairs,
      timeout_seconds: s.timeout_seconds ?? 10,
      tools: (s.tools ?? []).map((t) =>
        typeof t === 'string' ? { name: t, description: '', enabled: true } : { name: t.name, description: t.description ?? '', enabled: t.enabled ?? true },
      ),
      verified: s.verified ?? false,
    });
    setDirty(false);
    setTestError('');
  }, [selectedIdx, servers, isNew]);

  const markDirty = useCallback(() => setDirty(true), []);

  const startNew = useCallback(() => {
    setIsNew(true);
    setSelectedIdx(-1);
    setForm({ ...EMPTY });
    setDirty(false);
    setTestError('');
    setMcpTab('config');
  }, []);

  const cancelEdit = useCallback(() => {
    setIsNew(false);
    setSelectedIdx(servers.length > 0 ? 0 : null);
    setDirty(false);
    setTestError('');
  }, [servers]);

  const parseEnv = useCallback((text: string): Record<string, string> => {
    const env: Record<string, string> = {};
    for (const line of text.split('\n')) {
      const eq = line.indexOf('=');
      if (eq > 0) {
        env[line.slice(0, eq).trim()] = line.slice(eq + 1).trim();
      }
    }
    return env;
  }, []);

  const buildEntry = useCallback((f: ServerForm): MCPServer => {
    const env = parseEnv(f.envText);
    const entry: MCPServer = {
      name: f.name.trim(),
      transport: f.transport,
      timeout_seconds: f.timeout_seconds,
      verified: f.verified,
      tools: f.tools.length > 0 ? f.tools.map((t): MCPToolConfig => ({ name: t.name, description: t.description ?? '', enabled: t.enabled })) : undefined,
    };
    if (f.transport === 'stdio') {
      entry.command = f.command;
    } else {
      entry.url = f.url;
    }
    if (Object.keys(env).length > 0) {
      entry.env = env;
    }
    return entry;
  }, [parseEnv]);

  const handleSave = useCallback(async (f?: ServerForm) => {
    setSaving(true);
    try {
      const entry = buildEntry(f ?? form);
      const updated = isNew ? [...servers, entry] : servers.map((s, i) => (i === selectedIdx ? entry : s));
      const saved = await saveMCPServers(updated);
      setServers(saved);
      setIsNew(false);
      const newIdx = isNew ? saved.length - 1 : selectedIdx;
      setSelectedIdx(newIdx);
      setDirty(false);
    } finally {
      setSaving(false);
    }
  }, [form, isNew, selectedIdx, servers, buildEntry]);

  const handleDelete = useCallback(async () => {
    if (selectedIdx === null) return;
    const updated = servers.filter((_, i) => i !== selectedIdx);
    const saved = await saveMCPServers(updated);
    setServers(saved);
    setSelectedIdx(saved.length > 0 ? 0 : null);
    setDirty(false);
  }, [selectedIdx, servers]);

  const handleTest = useCallback(async () => {
    setTesting(true);
    setTestError('');
    try {
      const env = parseEnv(form.envText);
      const result = await testMCPConnection({
        transport: form.transport,
        command: form.transport === 'stdio' ? form.command : undefined,
        url: form.transport !== 'stdio' ? form.url : undefined,
        env: Object.keys(env).length > 0 ? env : undefined,
        timeout_seconds: form.timeout_seconds,
      });
      if (result.ok && result.tools) {
        const existing = new Map(form.tools.map((t) => [t.name, t.enabled]));
        const newTools = result.tools.map((t) => ({
          name: t.name,
          description: t.description,
          enabled: existing.has(t.name) ? (existing.get(t.name) ?? true) : true,
        }));
        const updated = { ...form, tools: newTools, verified: true };
        setForm(updated);
        await handleSave(updated);
        setMcpTab('tools');
      } else {
        setForm((f) => ({ ...f, verified: false }));
        setTestError(result.error ?? 'Unknown error');
      }
    } catch (e) {
      setTestError(e instanceof Error ? e.message : 'Connection failed');
    } finally {
      setTesting(false);
    }
  }, [form, parseEnv, handleSave]);

  const toggleTool = useCallback((toolName: string) => {
    setForm((f) => ({
      ...f,
      tools: f.tools.map((t) => (t.name === toolName ? { ...t, enabled: !t.enabled } : t)),
    }));
    setDirty(true);
  }, []);

  const transportLabel: Record<Transport, string> = {
    stdio: 'Stdio (local command)',
    sse: 'SSE (HTTP)',
    'streamable-http': 'Streamable HTTP',
  };

  return (
    <section className="page-frame">
      <header className="page-header">
        <div>
          <h1>{t('mcp.title')}</h1>
          <p>{t('mcp.subtitle')}</p>
        </div>
      </header>

      <div className="models-layout">
        <div className="models-sidebar">
          {servers.map((s, idx) => (
            <button
              key={s.name}
              type="button"
              className={`models-sidebar-item ${idx === selectedIdx && !isNew ? 'active' : ''}`}
              onClick={() => { setIsNew(false); setSelectedIdx(idx); setMcpTab('config'); }}
            >
              <div className="mcp-sidebar-row">
                <span className={`ws-status ${s.verified ? 'ok' : ((s.tools?.length ?? 0) > 0 ? 'unknown' : '')}`} />
                <strong>{s.name}</strong>
              </div>
              <span className="models-sidebar-meta">
                {s.transport} · {(Array.isArray(s.tools) ? s.tools.length : 0)} tools
              </span>
            </button>
          ))}
          <button type="button" className="models-sidebar-item add" onClick={startNew}>
            + Add Server
          </button>
        </div>

        <div className="models-editor">
          {(selectedIdx !== null || isNew) ? (
            <>
              <div className="models-editor-header">
                <h2>{isNew ? 'New MCP Server' : form.name || 'Server'}</h2>
                <div className="models-editor-header-actions">
                  {form.verified && <span className="mcp-status-badge ok">{t('mcp.connected')}</span>}
                  {!form.verified && !isNew && <span className="mcp-status-badge unknown">{t('mcp.notVerified')}</span>}
                  {!isNew && (
                    <button type="button" className="btn-delete" onClick={() => void handleDelete()}>
                      Delete
                    </button>
                  )}
                </div>
              </div>

              <div className="mcp-tabs" role="tablist">
                <button
                  type="button"
                  role="tab"
                  aria-selected={mcpTab === 'config'}
                  className={mcpTab === 'config' ? 'tab active' : 'tab'}
                  onClick={() => setMcpTab('config')}
                >
                  Config
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={mcpTab === 'tools'}
                  className={mcpTab === 'tools' ? 'tab active' : 'tab'}
                  onClick={() => setMcpTab('tools')}
                >
                  Tools {form.tools.length > 0 ? `(${form.tools.filter((t) => t.enabled).length}/${form.tools.length})` : ''}
                </button>
              </div>

              <div className="models-form">
                {mcpTab === 'config' && (
                  <>
                    <label className="settings-label">
                      Name
                      <input
                        className="settings-input"
                        value={form.name}
                        onChange={(e) => { setForm((f) => ({ ...f, name: e.target.value })); markDirty(); }}
                        placeholder="my-mcp-server"
                      />
                    </label>

                    <label className="settings-label">
                      Transport
                      <select
                        className="settings-select"
                        value={form.transport}
                        onChange={(e) => { setForm((f) => ({ ...f, transport: e.target.value as Transport, verified: false })); markDirty(); }}
                      >
                        {(Object.entries(transportLabel) as [Transport, string][]).map(([k, v]) => (
                          <option key={k} value={k}>{v}</option>
                        ))}
                      </select>
                    </label>

                    {form.transport === 'stdio' ? (
                      <label className="settings-label">
                        Command
                        <input
                          className="settings-input"
                          value={form.command}
                          onChange={(e) => { setForm((f) => ({ ...f, command: e.target.value, verified: false })); markDirty(); }}
                          placeholder="npx -y @modelcontextprotocol/server-filesystem /path"
                        />
                      </label>
                    ) : (
                      <label className="settings-label">
                        URL
                        <input
                          className="settings-input"
                          value={form.url}
                          onChange={(e) => { setForm((f) => ({ ...f, url: e.target.value, verified: false })); markDirty(); }}
                          placeholder="http://localhost:3001/mcp"
                        />
                      </label>
                    )}

                    <label className="settings-label">
                      Environment Variables
                      <textarea
                        className="settings-textarea"
                        value={form.envText}
                        onChange={(e) => { setForm((f) => ({ ...f, envText: e.target.value })); markDirty(); }}
                        placeholder={"KEY=value\nONE_PER_LINE=true"}
                        rows={3}
                      />
                    </label>

                    <label className="settings-label">
                      Timeout (seconds)
                      <input
                        className="settings-input"
                        type="number"
                        min={1}
                        value={form.timeout_seconds}
                        onChange={(e) => { setForm((f) => ({ ...f, timeout_seconds: parseInt(e.target.value) || 10 })); markDirty(); }}
                      />
                    </label>
                    {testError && <span className="mcp-test-error">{testError}</span>}
                  </>
                )}

                {mcpTab === 'tools' && (
                  <>
                    {form.tools.length > 0 ? (
                      <div className="skills-picker">
                        {form.tools.map((t) => (
                          <label key={t.name} className={`skill-pick ${t.enabled ? 'checked' : ''}`}>
                            <input
                              type="checkbox"
                              checked={t.enabled}
                              onChange={() => toggleTool(t.name)}
                            />
                            <span className="skill-pick-name">{t.name}</span>
                            <span className="skill-pick-desc">{t.description}</span>
                          </label>
                        ))}
                      </div>
                    ) : (
                      <p className="skill-empty">
                        {form.verified
                          ? 'No tools available from this server.'
                          : 'Test connection first to discover available tools.'}
                      </p>
                    )}
                  </>
                )}
              </div>

              <div className="settings-footer">
                {dirty && <span className="settings-dirty">{t('mcp.unsavedChanges')}</span>}
                {isNew && (
                  <button type="button" className="btn-secondary" onClick={cancelEdit}>Cancel</button>
                )}
                <button
                  type="button"
                  className="btn-secondary"
                  disabled={testing || (!form.command && !form.url)}
                  onClick={() => void handleTest()}
                >
                  {testing ? 'Testing...' : 'Test Connection'}
                </button>
                <button
                  type="button"
                  className="primary-button"
                  disabled={saving || !dirty || !form.name.trim()}
                  onClick={() => void handleSave()}
                >
                  {saving ? 'Saving...' : 'Save'}
                </button>
              </div>
            </>
          ) : (
            <div className="models-empty">
              <p>{t('mcp.selectServer')}</p>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
