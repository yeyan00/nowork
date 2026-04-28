/**
 * WorkerSettingsPanel — shared worker settings UI.
 *
 * Used by:
 *   - WorkersManager (inline in page layout)
 *   - WorkerSettingsSidebar (floating sidebar in chat)
 *
 * This component is self-contained: it loads catalog data (providers, skills,
 * tools, MCP servers, knowledge bases) and manages all setting state internally.
 */

import { useCallback, useEffect, useState } from 'react';
import { useI18n } from '../i18n';
import {
  addUserMemory,
  deleteUserMemory,
  getUserMemory,
  getUserProfile,
  listKnowledgeBases,
  listMCPServers,
  listModels,
  listSkills,
  listToolsCatalog,
  updateUserMemory,
  updateWorker,
} from '../lib/backend';
import type { KnowledgeBase, MCPServer, ProviderInfo, SkillSummary, ToolCatalogEntry } from '../lib/backend';
import type { WorkerSummary } from '../types';

export type ConfigSection = 'basic' | 'tools' | 'skills' | 'workspace' | 'model' | 'mcp' | 'knowledge' | 'learning' | 'members';

const ALL_NAV_ITEMS: { id: ConfigSection; labelKey: string; icon: string }[] = [
  { id: 'basic', labelKey: 'workerSettings.instructions', icon: '⚙' },
  { id: 'model', labelKey: 'workerSettings.model', icon: '🤖' },
  { id: 'tools', labelKey: 'workerSettings.tools', icon: '🔧' },
  { id: 'workspace', labelKey: 'workerSettings.workspace', icon: '📁' },
  { id: 'mcp', labelKey: 'workerSettings.mcpServers', icon: '🔌' },
  { id: 'knowledge', labelKey: 'workerSettings.knowledgeBases', icon: '📖' },
  { id: 'skills', labelKey: 'workerSettings.skills', icon: '🧠' },
  { id: 'learning', labelKey: 'workerSettings.learning', icon: '📚' },
];

export { ALL_NAV_ITEMS };

interface WorkspaceEntry { path: string; permission: string }
interface ToolSelection { enabled: boolean; subTools: Record<string, boolean> }

export interface WorkerSettingsPanelProps {
  worker: WorkerSummary;
  onSave?: (savedWorker: WorkerSummary) => void;
  /** Extra nav items to show (e.g. 'members' for Teams). */
  extraSections?: ConfigSection[];
  /** Pre-loaded agents list (for Team members section). */
  allAgents?: WorkerSummary[];
  /** Nav layout: horizontal (sidebar) or vertical (page). */
  navLayout?: 'horizontal' | 'vertical';
}

export function WorkerSettingsPanel({
  worker,
  onSave,
  extraSections,
  allAgents: externalAgents,
  navLayout = 'horizontal',
}: WorkerSettingsPanelProps) {
  const { t } = useI18n();
  const [section, setSection] = useState<ConfigSection>('basic');
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');
  const [dirty, setDirty] = useState(false);

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [instructions, setInstructions] = useState('');
  const [selectedSkills, setSelectedSkills] = useState<string[]>([]);
  const [workspaces, setWorkspaces] = useState<WorkspaceEntry[]>([]);
  const [newWsPath, setNewWsPath] = useState('');
  const [defaultReadable, setDefaultReadable] = useState(true);
  const [modelRef, setModelRef] = useState('');
  const [toolSelections, setToolSelections] = useState<Record<string, ToolSelection>>({});
  const [members, setMembers] = useState<{ agent_id: string; role: string }[]>([]);

  const [learningUserProfile, setLearningUserProfile] = useState(true);
  const [learningUserMemory, setLearningUserMemory] = useState(true);
  const [learningSessionContext, setLearningSessionContext] = useState(false);
  const [learningEntityMemory, setLearningEntityMemory] = useState(false);
  const [learningDecisionLog, setLearningDecisionLog] = useState(false);

  const [selectedMCPs, setSelectedMCPs] = useState<string[]>([]);
  const [selectedKnowledge, setSelectedKnowledge] = useState<string[]>([]);
  const [learningUserId, setLearningUserId] = useState('default');
  const [profileData, setProfileData] = useState<Record<string, unknown> | null>(null);
  const [memoryData, setMemoryData] = useState<Array<Record<string, unknown>>>([]);
  const [learningTab, setLearningTab] = useState<'profile' | 'memory'>('profile');
  const [editingMemoryId, setEditingMemoryId] = useState<string | null>(null);
  const [editMemoryText, setEditMemoryText] = useState('');
  const [newMemoryText, setNewMemoryText] = useState('');

  // Catalogs
  const [allSkills, setAllSkills] = useState<SkillSummary[]>([]);
  const [allMCPServers, setAllMCPServers] = useState<MCPServer[]>([]);
  const [allKnowledgeBases, setAllKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [toolsCatalog, setToolsCatalog] = useState<ToolCatalogEntry[]>([]);

  // Load catalogs once
  useEffect(() => {
    void listSkills().then(setAllSkills).catch(() => {});
    void listModels().then((r) => setProviders(r.providers)).catch(() => {});
    void listToolsCatalog().then(setToolsCatalog).catch(() => {});
    void listMCPServers().then(setAllMCPServers).catch(() => {});
    void listKnowledgeBases().then(setAllKnowledgeBases).catch(() => {});
  }, []);

  // Load worker config
  useEffect(() => {
    const cfg = (worker.config ?? {}) as unknown as Record<string, unknown>;
    setName(worker.name);
    setDescription(worker.description);
    setInstructions((cfg['instructions'] as string) ?? '');
    setSelectedSkills((cfg['skills'] as string[]) ?? []);
    setModelRef((cfg['model'] as string) ?? '');

    const wsRaw = (cfg['workspaces'] as Array<Record<string, string>>) ?? [];
    setWorkspaces(wsRaw.map((w) => ({ path: w.path, permission: w.permission })));

    // Read default_readable from tools config
    const _toolsRaw = (cfg['tools'] as Array<Record<string, unknown>>) ?? [];
    const codingCfg = _toolsRaw.find((t) => t.class === 'CodingTools');
    const toolsConfig = (codingCfg?.config ?? {}) as Record<string, unknown>;
    setDefaultReadable(toolsConfig['default_readable'] !== false);

    const membersRaw = (cfg['members'] as Array<Record<string, unknown>>) ?? [];
    setMembers(membersRaw.map((m) => ({ agent_id: (m['agent_id'] as string) ?? '', role: (m['role'] as string) ?? '' })));

    setSelectedMCPs((cfg['mcp'] as string[]) ?? []);
    setSelectedKnowledge((cfg['knowledge'] as string[]) ?? []);

    const learning = (cfg['learning'] as unknown as Record<string, unknown>) ?? {};
    setLearningUserProfile((learning['user_profile'] as boolean) ?? true);
    setLearningUserMemory((learning['user_memory'] as boolean) ?? true);
    setLearningSessionContext((learning['session_context'] as boolean) ?? false);
    setLearningEntityMemory((learning['entity_memory'] as boolean) ?? false);
    setLearningDecisionLog((learning['decision_log'] as boolean) ?? false);

    // Tools
    const toolsRaw = (cfg['tools'] as Array<Record<string, unknown>>) ?? [];
    setToolSelections(() => {
      const sel: Record<string, ToolSelection> = {};
      for (const cat of toolsCatalog.length > 0 ? toolsCatalog : []) {
        const match = toolsRaw.find((t) => t.module === cat.module && t.class === cat.name);
        const subTools: Record<string, boolean> = {};
        const cfgAny = (match?.config ?? {}) as unknown as Record<string, unknown>;
        const allFlag = cfgAny['all'] as boolean;
        for (const st of cat.tools) {
          subTools[st.id] = allFlag ? true : match ? (cfgAny[`enable_${st.id}`] as boolean) ?? st.default : st.default;
        }
        sel[cat.id] = { enabled: !!match, subTools };
      }
      return sel;
    });

    setDirty(false);
  }, [worker, toolsCatalog]);

  // Re-derive tools when catalog loads after worker config
  useEffect(() => {
    if (toolsCatalog.length === 0) return;
    const cfg = (worker.config ?? {}) as unknown as Record<string, unknown>;
    const toolsRaw = (cfg['tools'] as Array<Record<string, unknown>>) ?? [];
    setToolSelections(() => {
      const sel: Record<string, ToolSelection> = {};
      for (const cat of toolsCatalog) {
        const match = toolsRaw.find((t) => t.module === cat.module && t.class === cat.name);
        const subTools: Record<string, boolean> = {};
        const cfgAny = (match?.config ?? {}) as unknown as Record<string, unknown>;
        const allFlag = cfgAny['all'] as boolean;
        for (const st of cat.tools) {
          subTools[st.id] = allFlag ? true : match ? (cfgAny[`enable_${st.id}`] as boolean) ?? st.default : st.default;
        }
        sel[cat.id] = { enabled: !!match, subTools };
      }
      return sel;
    });
  }, [toolsCatalog, worker.config]);

  // Load learning data
  useEffect(() => {
    void (async () => {
      try { const p = await getUserProfile(worker.id, learningUserId); setProfileData(((p as unknown as Record<string, unknown>).profile as unknown as Record<string, unknown>) ?? null); } catch { setProfileData(null); }
      try { const m = await getUserMemory(worker.id, learningUserId); setMemoryData(((m as unknown as Record<string, unknown>).memories as Array<Record<string, unknown>>) ?? []); } catch { setMemoryData([]); }
    })();
  }, [worker.id, learningUserId]);

  const markDirty = useCallback(() => setDirty(true), []);

  const toggleSkill = useCallback((s: string) => {
    setSelectedSkills((prev) => { const next = prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s]; setDirty(true); return next; });
  }, []);

  const toggleTool = useCallback((catId: string, subId?: string) => {
    setToolSelections((prev) => {
      const cat = prev[catId] ?? { enabled: false, subTools: Object.fromEntries((toolsCatalog.find((c) => c.id === catId)?.tools ?? []).map((t) => [t.id, t.default])) };
      if (subId) return { ...prev, [catId]: { ...cat, subTools: { ...cat.subTools, [subId]: !cat.subTools[subId] } } };
      return { ...prev, [catId]: { ...cat, enabled: !cat.enabled } };
    });
    setDirty(true);
  }, [toolsCatalog]);

  const addWorkspace = useCallback(() => { const p = newWsPath.trim(); if (!p) return; setWorkspaces((prev) => [...prev, { path: p, permission: 'read-write' }]); setNewWsPath(''); setDirty(true); }, [newWsPath]);
  const removeWorkspace = useCallback((idx: number) => { setWorkspaces((prev) => prev.filter((_, i) => i !== idx)); setDirty(true); }, []);
  const updateWorkspacePerm = useCallback((idx: number, perm: string) => { setWorkspaces((prev) => prev.map((w, i) => (i === idx ? { ...w, permission: perm } : w))); setDirty(true); }, []);

  const buildToolsPayload = useCallback((): unknown[] => {
    const result: unknown[] = [];
    for (const cat of toolsCatalog) {
      const sel = toolSelections[cat.id];
      const isRequired = cat.id === 'coding-tools';
      if (!isRequired && (!sel || !sel.enabled)) continue;
      const baseDirs = workspaces.map((w) => w.path);
      const config: Record<string, unknown> = { base_dirs: baseDirs.length > 0 ? baseDirs : undefined, default_readable: defaultReadable };
      const allOn = cat.tools.every((t) => sel?.subTools[t.id] || t.required);
      if (allOn) { config['all'] = true; } else { for (const t of cat.tools) { config[`enable_${t.id}`] = !!sel?.subTools[t.id]; } }
      result.push({ module: cat.module, class: cat.name, config });
    }
    return result;
  }, [toolsCatalog, toolSelections, workspaces, defaultReadable]);

  const handleSave = useCallback(async () => {
    setSaving(true);
    setSaveError('');
    try {
      const saved = await updateWorker(worker.id, {
        name, description,
        config: {
          model: modelRef || undefined,
          instructions: instructions || undefined,
          skills: selectedSkills.length > 0 ? selectedSkills : undefined,
          workspaces: workspaces.length > 0 ? workspaces : undefined,
          tools: buildToolsPayload().length > 0 ? buildToolsPayload() : undefined,
          members: worker.type === 'Team' && members.length > 0 ? members : undefined,
          mcp: selectedMCPs.length > 0 ? selectedMCPs : undefined,
          knowledge: selectedKnowledge.length > 0 ? selectedKnowledge : undefined,
          learning: { user_profile: learningUserProfile, user_memory: learningUserMemory, session_context: learningSessionContext, entity_memory: learningEntityMemory, decision_log: learningDecisionLog },
        },
      });
      setDirty(false);
      onSave?.(saved);
    } catch (e) { setSaveError(e instanceof Error ? e.message : 'Save failed'); } finally { setSaving(false); }
  }, [worker.id, worker.type, name, description, modelRef, instructions, selectedSkills, workspaces, buildToolsPayload, members, selectedMCPs, selectedKnowledge, learningUserProfile, learningUserMemory, learningSessionContext, learningEntityMemory, learningDecisionLog, onSave]);

  const selectedProvider = providers.find((p) => modelRef ? modelRef.startsWith(`${p.id}/`) : false);

  const dirExists = useCallback((p: string) => { try { return p.length > 0 && /^[A-Za-z]:\\|^\/|^~/.test(p); } catch { return false; } }, []);

  const navItems = [
    ...ALL_NAV_ITEMS,
    ...(worker.type === 'Team' ? [{ id: 'members' as ConfigSection, labelKey: 'workerSettings.members', icon: '👥' }] : []),
    ...(extraSections ?? []).filter((s) => !ALL_NAV_ITEMS.some((n) => n.id === s) && s !== 'members').map((s) => ({ id: s, labelKey: '', icon: '•' })),
  ];

  const agents = externalAgents ?? [];

  return (
    <div className={navLayout === 'vertical' ? 'wsp-vertical' : 'wsp-horizontal'}>
      <nav className={navLayout === 'vertical' ? 'settings-nav' : 'ws-sidebar-nav'}>
        {navItems.map((item) => (
          <button key={item.id} type="button" className={navLayout === 'vertical' ? `settings-nav-item ${section === item.id ? 'active' : ''}` : `ws-sidebar-nav-item ${section === item.id ? 'active' : ''}`} onClick={() => setSection(item.id)}>
            <span>{item.icon}</span><span>{item.labelKey ? t(item.labelKey) : item.id}</span>
          </button>
        ))}
      </nav>

      <div className={navLayout === 'vertical' ? 'settings-body' : 'ws-sidebar-body'}>
        {saveError && <div className="form-error">{saveError}</div>}

        {section === 'basic' && (
          <div className="settings-section">
            <div className="settings-form">
              <label className="settings-label">Name<input className="settings-input" value={name} onChange={(e) => { setName(e.target.value); markDirty(); }} /></label>
              <label className="settings-label">Description<input className="settings-input" value={description} onChange={(e) => { setDescription(e.target.value); markDirty(); }} /></label>
            </div>
            <h3 className="settings-section-title">{t('workerSettings.instructions')}</h3>
            <textarea className="settings-textarea" value={instructions} onChange={(e) => { setInstructions(e.target.value); markDirty(); }} placeholder="Agent instructions (system prompt)..." rows={8} />
          </div>
        )}

        {section === 'model' && (
          <div className="settings-section">
            <h3 className="settings-section-title">{t('workerSettings.model')}</h3>
            <div className="settings-form">
              <label className="settings-label">{t('workerSettings.provider')}<select className="settings-select" value={selectedProvider?.id ?? ''} onChange={(e) => { const prov = providers.find((p) => p.id === e.target.value); if (prov?.models.length) setModelRef(prov.models[0].id); else setModelRef(''); markDirty(); }}><option value="">{t('workerSettings.selectProvider')}</option>{providers.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
              <label className="settings-label">{t('workerSettings.modelLabel')}<select className="settings-select" value={modelRef} onChange={(e) => { setModelRef(e.target.value); markDirty(); }} disabled={!selectedProvider}><option value="">{t('workerSettings.selectModel')}</option>{selectedProvider?.models.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}</select></label>
            </div>
          </div>
        )}

        {section === 'tools' && (
          <div className="settings-section">
            <h3 className="settings-section-title">{t('workerSettings.tools')}</h3>
            {toolsCatalog.map((cat) => {
              const sel = toolSelections[cat.id];
              const enabled = sel?.enabled ?? false;
              // CodingTools is always required — skip the enable toggle
              const isRequired = cat.id === 'coding-tools';
              const showTools = isRequired || enabled;
              return (
                <div key={cat.id} className="tool-card">
                  <label className="tool-card-header">
                    <input type="checkbox" checked={isRequired || enabled} onChange={() => { if (!isRequired) toggleTool(cat.id); }} disabled={isRequired} />
                    <div className="tool-card-info"><strong>{cat.name}</strong><span className="tool-card-desc">{cat.description}</span></div>
                  </label>
                  {showTools && (<div className="tool-sub-list">{cat.tools.map((st) => (<label key={st.id} className={`tool-sub-item${st.required ? ' tool-required' : ''}`}><input type="checkbox" checked={sel?.subTools[st.id] ?? st.default} onChange={() => toggleTool(cat.id, st.id)} disabled={st.required} /><span>{st.name}{st.required ? ' *' : ''}</span></label>))}</div>)}
                </div>
              );
            })}
          </div>
        )}

        {section === 'workspace' && (
          <div className="settings-section">
            <h3 className="settings-section-title">{t('workerSettings.workspace')}</h3>
            <div className="ws-list">
              {workspaces.map((ws, idx) => (
                <div key={idx} className="ws-card">
                  <span className={`ws-status ${dirExists(ws.path) ? 'ok' : 'unknown'}`} />
                  <span className="ws-path" title={ws.path}>{ws.path}</span>
                  <select className="ws-perm" value={ws.permission} onChange={(e) => updateWorkspacePerm(idx, e.target.value)}><option value="read-write">{t('workerSettings.readWrite')}</option><option value="read-only">{t('workerSettings.readOnly')}</option></select>
                  <button type="button" className="ws-remove" onClick={() => removeWorkspace(idx)}>✕</button>
                </div>
              ))}
            </div>
            <div className="ws-add-row">
              <input className="ws-add-input" value={newWsPath} onChange={(e) => setNewWsPath(e.target.value)} placeholder="C:/my-project" onKeyDown={(e) => { if (e.key === 'Enter') addWorkspace(); }} />
              <button type="button" className="ws-add-btn" onClick={addWorkspace}>{t('workerSettings.add')}</button>
            </div>
            <div className="ws-option-row">
              <label className="ws-option-label">
                <input type="checkbox" checked={defaultReadable} onChange={(e) => { setDefaultReadable(e.target.checked); setDirty(true); }} />
                <span>{t('workerSettings.defaultReadable')}</span>
              </label>
              <span className="ws-option-hint">{t('workerSettings.defaultReadableHint')}</span>
            </div>
          </div>
        )}

        {section === 'mcp' && (
          <div className="settings-section">
            <h3 className="settings-section-title">{t('workerSettings.mcpServers')}</h3>
            <div className="skills-picker">
              {allMCPServers.filter((s) => s.verified).map((s) => { const checked = selectedMCPs.includes(s.name); return (<label key={s.name} className={`skill-pick ${checked ? 'checked' : ''}`}><input type="checkbox" checked={checked} onChange={() => { setSelectedMCPs((prev) => checked ? prev.filter((n) => n !== s.name) : [...prev, s.name]); setDirty(true); }} /><span className="skill-pick-name">{s.name}</span><span className="skill-pick-desc">{s.transport} — {s.command ?? s.url ?? ''}</span></label>); })}
              {allMCPServers.filter((s) => s.verified).length === 0 && <p className="skill-empty">{t('workerSettings.noMcp')}</p>}
            </div>
          </div>
        )}

        {section === 'knowledge' && (
          <div className="settings-section">
            <h3 className="settings-section-title">{t('workerSettings.knowledgeBases')}</h3>
            <div className="skills-picker">
              {allKnowledgeBases.map((kb) => { const checked = selectedKnowledge.includes(kb.id); return (<label key={kb.id} className={`skill-pick ${checked ? 'checked' : ''}`}><input type="checkbox" checked={checked} onChange={() => { setSelectedKnowledge((prev) => checked ? prev.filter((id) => id !== kb.id) : [...prev, kb.id]); setDirty(true); }} /><span className="skill-pick-name">{kb.name || kb.id}</span><span className="skill-pick-desc">{(kb.paths ?? []).length} paths</span></label>); })}
              {allKnowledgeBases.length === 0 && <p className="skill-empty">{t('workerSettings.noKnowledge')}</p>}
            </div>
          </div>
        )}

        {section === 'skills' && (
          <div className="settings-section">
            <h3 className="settings-section-title">{t('workerSettings.skills')}</h3>
            <div className="skills-picker">
              {allSkills.map((s) => (<label key={s.name} className={`skill-pick ${selectedSkills.includes(s.name) ? 'checked' : ''}`}><input type="checkbox" checked={selectedSkills.includes(s.name)} onChange={() => toggleSkill(s.name)} /><span className="skill-pick-name">{s.name}</span><span className="skill-pick-desc">{s.description.slice(0, 60)}…</span></label>))}
              {allSkills.length === 0 && <p className="skill-empty">{t('workerSettings.noSkills')}</p>}
            </div>
          </div>
        )}

        {section === 'learning' && (
          <div className="settings-section">
            <h3 className="settings-section-title">{t('workerSettings.learning')}</h3>
            <div className="skills-picker">
              {([
                { key: 'user_profile', label: 'User Profile', desc: 'Structured profile fields.', state: learningUserProfile, setter: setLearningUserProfile },
                { key: 'user_memory', label: 'User Memory', desc: 'Unstructured observations.', state: learningUserMemory, setter: setLearningUserMemory },
                { key: 'session_context', label: 'Session Context', desc: 'Current session state.', state: learningSessionContext, setter: setLearningSessionContext },
                { key: 'entity_memory', label: 'Entity Memory', desc: 'Facts about entities.', state: learningEntityMemory, setter: setLearningEntityMemory },
                { key: 'decision_log', label: 'Decision Log', desc: 'Agent decisions.', state: learningDecisionLog, setter: setLearningDecisionLog },
              ] as const).map((item) => (<label key={item.key} className={`skill-pick ${item.state ? 'checked' : ''}`}><input type="checkbox" checked={item.state} onChange={() => { item.setter(!item.state); markDirty(); }} /><span className="skill-pick-name">{item.label}</span><span className="skill-pick-desc">{item.desc}</span></label>))}
            </div>
            <div style={{ marginTop: '1.5rem', borderTop: '1px solid rgba(132,146,170,0.15)', paddingTop: '1rem' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '0.75rem' }}>
                <h4 style={{ margin: 0, fontSize: '14px', color: '#31415d' }}>{t('workerSettings.learnedData')}</h4>
                <input className="settings-input" style={{ width: '160px', fontSize: '12px', padding: '4px 8px' }} value={learningUserId} onChange={(e) => setLearningUserId(e.target.value)} placeholder="user_id" />
                <div style={{ display: 'flex', gap: '4px' }}>
                  <button type="button" className={`tab ${learningTab === 'profile' ? 'active' : ''}`} style={{ padding: '4px 10px', fontSize: '12px' }} onClick={() => setLearningTab('profile')}>{t('workerSettings.profile')}</button>
                  <button type="button" className={`tab ${learningTab === 'memory' ? 'active' : ''}`} style={{ padding: '4px 10px', fontSize: '12px' }} onClick={() => setLearningTab('memory')}>{t('workerSettings.memory')}</button>
                </div>
              </div>
              {learningTab === 'profile' && (<div style={{ background: 'rgba(0,0,0,0.03)', borderRadius: '8px', padding: '12px' }}>{profileData ? <pre style={{ margin: 0, fontSize: '12px', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{JSON.stringify(profileData, null, 2)}</pre> : <span style={{ color: '#888', fontSize: '12px' }}>{t('workerSettings.noProfile')}</span>}</div>)}
              {learningTab === 'memory' && (
                <div>
                  {memoryData.map((mem, idx) => {
                    const memId = String(mem.memory_id ?? mem.id ?? idx);
                    const isEditing = editingMemoryId === memId;
                    return (
                      <div key={memId} style={{ background: 'rgba(0,0,0,0.03)', borderRadius: '8px', padding: '10px', marginBottom: '8px' }}>
                        {isEditing ? (
                          <div>
                            <textarea className="settings-textarea" rows={3} style={{ fontSize: '12px' }} value={editMemoryText} onChange={(e) => setEditMemoryText(e.target.value)} />
                            <div style={{ marginTop: '6px', display: 'flex', gap: '6px' }}>
                              <button type="button" className="primary-button" style={{ padding: '4px 12px', fontSize: '12px' }} onClick={() => { void updateUserMemory(worker.id, memId, editMemoryText).then(() => { setEditingMemoryId(null); void getUserMemory(worker.id, learningUserId).then((r) => { setMemoryData(((r as unknown as Record<string, unknown>).memories as Array<Record<string, unknown>>) ?? []); }); }); }}>{t('workerSettings.save')}</button>
                              <button type="button" style={{ padding: '4px 12px', fontSize: '12px' }} onClick={() => setEditingMemoryId(null)}>{t('workerSettings.cancel')}</button>
                            </div>
                          </div>
                        ) : (
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                            <span style={{ fontSize: '12px', whiteSpace: 'pre-wrap', wordBreak: 'break-word', flex: 1 }}>{String(mem.memory ?? mem.content ?? mem)}</span>
                            <div style={{ display: 'flex', gap: '4px', marginLeft: '8px', flexShrink: 0 }}>
                              <button type="button" style={{ fontSize: '11px', padding: '2px 6px', cursor: 'pointer' }} onClick={() => { setEditingMemoryId(memId); setEditMemoryText(String(mem.memory ?? mem.content ?? '')); }}>{t('workerSettings.edit')}</button>
                              <button type="button" style={{ fontSize: '11px', padding: '2px 6px', color: '#d32f2f', cursor: 'pointer' }} onClick={() => { void deleteUserMemory(worker.id, memId, learningUserId).then(() => { setMemoryData((prev) => prev.filter((_, i) => i !== idx)); }); }}>{t('workerSettings.delete')}</button>
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                  <div style={{ display: 'flex', gap: '8px', marginTop: '8px' }}>
                    <input className="settings-input" style={{ flex: 1, fontSize: '12px', padding: '6px 10px' }} value={newMemoryText} onChange={(e) => setNewMemoryText(e.target.value)} placeholder="Add a new memory..." onKeyDown={(e) => { if (e.key === 'Enter' && newMemoryText.trim()) { void addUserMemory(worker.id, learningUserId, newMemoryText.trim()).then(() => { setNewMemoryText(''); void getUserMemory(worker.id, learningUserId).then((r) => { setMemoryData(((r as unknown as Record<string, unknown>).memories as Array<Record<string, unknown>>) ?? []); }); }); } }} />
                    <button type="button" className="primary-button" style={{ padding: '6px 14px', fontSize: '12px' }} disabled={!newMemoryText.trim()} onClick={() => { if (!newMemoryText.trim()) return; void addUserMemory(worker.id, learningUserId, newMemoryText.trim()).then(() => { setNewMemoryText(''); void getUserMemory(worker.id, learningUserId).then((r) => { setMemoryData(((r as unknown as Record<string, unknown>).memories as Array<Record<string, unknown>>) ?? []); }); }); }}>{t('workerSettings.add')}</button>
                  </div>
                  {memoryData.length === 0 && <span style={{ color: '#888', fontSize: '12px' }}>{t('workerSettings.noMemories')}</span>}
                </div>
              )}
            </div>
          </div>
        )}

        {section === 'members' && worker.type === 'Team' && (
          <div className="settings-section">
            <h3 className="settings-section-title">{t('workerSettings.members')}</h3>
            <div className="skills-picker">
              {agents.map((a) => { const checked = members.some((m) => m.agent_id === a.id); return (<label key={a.id} className={`skill-pick ${checked ? 'checked' : ''}`}><input type="checkbox" checked={checked} onChange={() => { if (checked) setMembers((prev) => prev.filter((m) => m.agent_id !== a.id)); else setMembers((prev) => [...prev, { agent_id: a.id, role: '' }]); setDirty(true); }} /><span className="skill-pick-name">{a.name}</span><span className="skill-pick-desc">{a.id}</span></label>); })}
              {agents.length === 0 && <p className="skill-empty">{t('workerSettings.noAgents')}</p>}
            </div>
          </div>
        )}
      </div>

      <div className={navLayout === 'vertical' ? 'settings-footer' : 'ws-sidebar-footer'}>
        {dirty && <span className="settings-dirty">{t('workerSettings.unsavedChanges')}</span>}
        {saveError && <span className="mcp-test-error">{saveError}</span>}
        <button type="button" className="primary-button" disabled={saving || !dirty} onClick={() => void handleSave()}>
          {saving ? 'Saving...' : 'Save'}
        </button>
      </div>
    </div>
  );
}
