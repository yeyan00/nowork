import { useCallback, useEffect, useState } from 'react';
import { useI18n } from '../i18n';
import { MarkdownContent } from './MarkdownContent';
import { WikiGraphView } from './WikiGraphView';
import {
  createKnowledgeBase,
  deleteKnowledgeBase,
  listKnowledgeBases,
  updateKnowledgeBase,
  reloadKnowledgeBase,
  syncWikiKnowledgeBase,
  cancelWikiSync,
  listWikiPages,
  readWikiPage,
  writeWikiPage,
  deleteWikiPage,
  searchWikiPages,
  getWikiStats,
  getWikiGraph,
} from '../lib/backend';
import type {
  KnowledgeBase,
  WikiPage,
  WikiPageSummary,
  WikiSearchResult,
  WikiStats,
  WikiGraphData,
} from '../lib/backend';

type DetailTab = 'settings' | 'pages' | 'search';

// Module-level sync state — survives component remount (page navigation)
let _activeSyncAbort: AbortController | null = null;

export function KnowledgePage() {
  const { t } = useI18n();
  const [items, setItems] = useState<KnowledgeBase[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState('');
  const [newWikiMode, setNewWikiMode] = useState(true);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  // ── Settings state ──
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [paths, setPaths] = useState('');
  const [purpose, setPurpose] = useState('');
  const [wikiMode, setWikiMode] = useState(false);
  const [autoSync, setAutoSync] = useState(false);
  const [language, setLanguage] = useState('');
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);

  // ── Wiki state ──
  const [detailTab, setDetailTab] = useState<DetailTab>('settings');
  const [wikiPages, setWikiPages] = useState<WikiPageSummary[]>([]);
  const [wikiStats, setWikiStats] = useState<WikiStats | null>(null);
  const [syncing, setSyncing] = useState(_activeSyncAbort !== null);
  const [selectedPagePath, setSelectedPagePath] = useState<string | null>(null);
  const [pageContent, setPageContent] = useState<WikiPage | null>(null);
  const [editingPage, setEditingPage] = useState(false);
  const [editContent, setEditContent] = useState('');
  const [pageFilter, setPageFilter] = useState('');
  const [pageType, setPageType] = useState('');
  const [newPagePath, setNewPagePath] = useState('');
  const [showNewPage, setShowNewPage] = useState(false);

  // ── Search state ──
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<WikiSearchResult[]>([]);
  const [searching, setSearching] = useState(false);

  const [graphData, setGraphData] = useState<WikiGraphData | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    void listKnowledgeBases()
      .then((kbs) => {
        setItems(kbs);
        if (kbs.length > 0 && !selectedId) setSelectedId(kbs[0].id);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [selectedId]);

  useEffect(() => { load(); }, []);

  const selected = items.find((kb) => kb.id === selectedId) ?? null;
  const isWiki = selected?.wiki_mode === true;

  // ── Sync settings from selected KB ──
  useEffect(() => {
    if (!selected) return;
    setName(selected.name);
    setDescription(selected.description);
    setPaths((selected.paths ?? []).join('\n'));
    setWikiMode(selected.wiki_mode ?? false);
    setPurpose(selected.purpose ?? '');
    setAutoSync(selected.auto_sync ?? false);
    setLanguage(selected.language ?? '');
    setDirty(false);
    setDetailTab(isWiki ? 'pages' : 'settings');
    setSelectedPagePath(null);
    setPageContent(null);
    setEditingPage(false);
  }, [selectedId, items]);

  // ── Load wiki data when selecting a wiki KB ──
  const loadWikiData = useCallback(() => {
    if (!selectedId || !isWiki) return;
    void listWikiPages(selectedId, pageType || undefined, pageFilter || undefined)
      .then(setWikiPages)
      .catch(() => setWikiPages([]));
    void getWikiStats(selectedId)
      .then(setWikiStats)
      .catch(() => setWikiStats(null));
    void getWikiGraph(selectedId)
      .then(setGraphData)
      .catch(() => setGraphData(null));
  }, [selectedId, isWiki, pageType, pageFilter]);

  useEffect(() => { loadWikiData(); }, [loadWikiData]);

  // ── Load page content ──
  useEffect(() => {
    if (!selectedId || !selectedPagePath || !isWiki) return;
    void readWikiPage(selectedId, selectedPagePath)
      .then((page) => {
        setPageContent(page);
        setEditContent(page.raw);
        setEditingPage(false);
      })
      .catch(() => setPageContent(null));
  }, [selectedId, selectedPagePath, isWiki]);

  const markDirty = useCallback(() => setDirty(true), []);

  const handleSave = useCallback(() => {
    if (!selectedId) return;
    setSaving(true);
    void updateKnowledgeBase(selectedId, {
      name,
      description,
      wiki_mode: wikiMode,
      purpose,
      auto_sync: autoSync,
      language,
      config: {
        paths: paths.split('\n').map((p) => p.trim()).filter(Boolean),
      },
    }).then((updated) => {
      setItems((prev) => prev.map((kb) => (kb.id === selectedId ? { ...kb, ...updated } : kb)));
      setDirty(false);
    }).catch(() => {}).finally(() => setSaving(false));
  }, [selectedId, name, description, wikiMode, purpose, autoSync, language, paths]);

  const handleCreate = useCallback(() => {
    if (!newName.trim()) return;
    void createKnowledgeBase({
      name: newName.trim(),
      wiki_mode: newWikiMode,
    } as Partial<KnowledgeBase>).then((kb) => {
      setItems((prev) => [...prev, kb]);
      setSelectedId(kb.id);
      setShowCreate(false);
      setNewName('');
    }).catch(() => {});
  }, [newName, newWikiMode]);

  const handleDelete = useCallback((id: string) => {
    void deleteKnowledgeBase(id).then(() => {
      setItems((prev) => prev.filter((kb) => kb.id !== id));
      if (selectedId === id) setSelectedId(items[0]?.id ?? null);
      setDeleteTarget(null);
    }).catch(() => {});
  }, [selectedId, items]);

  const handleReload = useCallback((id: string) => {
    void reloadKnowledgeBase(id).catch(() => {});
  }, []);

  const handleSync = useCallback(async () => {
    if (!selectedId) return;
    // If already syncing, cancel via backend + abort fetch
    if (_activeSyncAbort) {
      const ac = _activeSyncAbort;
      _activeSyncAbort = null;
      ac.abort();
      setSyncing(false);
      try {
        await cancelWikiSync(selectedId);
      } catch { /* best effort */ }
      return;
    }

    // Save language to backend first, then sync
    setSyncing(true);
    const ac = new AbortController();
    _activeSyncAbort = ac;

    try {
      // Save language setting before sync so backend reads the correct locale
      await updateKnowledgeBase(selectedId, { language });
      // Update local items list to reflect saved language
      setItems((prev) => prev.map((kb) => (kb.id === selectedId ? { ...kb, language } : kb)));

      const result = await syncWikiKnowledgeBase(selectedId, ac.signal);
      loadWikiData();
      if (result.cancelled) {
        alert('Sync cancelled. Partial results have been saved.');
      } else {
        alert(`Synced: ${result.pages_written} pages written`);
      }
    } catch (e: any) {
      if (e.name === 'AbortError') {
        // Frontend aborted — backend cancel was already called above.
        // Reload wiki data to show partial results.
        loadWikiData();
      } else {
        alert('Sync failed: ' + e.message);
      }
    } finally {
      if (_activeSyncAbort === ac) {
        _activeSyncAbort = null;
      }
      setSyncing(false);
    }
  }, [selectedId, language, loadWikiData]);

  const handleSavePage = useCallback(() => {
    if (!selectedId || !selectedPagePath) return;
    void writeWikiPage(selectedId, selectedPagePath, editContent)
      .then(() => {
        setEditingPage(false);
        // Reload page content
        void readWikiPage(selectedId, selectedPagePath)
          .then((page) => { setPageContent(page); setEditContent(page.raw); })
          .catch(() => {});
        loadWikiData();
      })
      .catch((e) => alert('Save failed: ' + e.message));
  }, [selectedId, selectedPagePath, editContent, loadWikiData]);

  const handleDeletePage = useCallback((pagePath: string) => {
    if (!selectedId || !confirm(t('knowledge.confirmDeletePage'))) return;
    void deleteWikiPage(selectedId, pagePath)
      .then(() => {
        if (selectedPagePath === pagePath) {
          setSelectedPagePath(null);
          setPageContent(null);
        }
        loadWikiData();
      })
      .catch(() => {});
  }, [selectedId, selectedPagePath, loadWikiData, t]);

  const handleNewPage = useCallback(() => {
    if (!selectedId || !newPagePath.trim()) return;
    const path = newPagePath.trim().startsWith('wiki/')
      ? newPagePath.trim()
      : `wiki/${newPagePath.trim()}`;
    const defaultContent = `---\ntype: entity\ntitle: ""\nsources: []\nrelated: []\n---\n\n`;
    void writeWikiPage(selectedId, path, defaultContent)
      .then(() => {
        setSelectedPagePath(path);
        setShowNewPage(false);
        setNewPagePath('');
        loadWikiData();
      })
      .catch((e) => alert('Create failed: ' + e.message));
  }, [selectedId, newPagePath, loadWikiData]);

  const handleSearch = useCallback(() => {
    if (!selectedId || !searchQuery.trim()) return;
    setSearching(true);
    void searchWikiPages(selectedId, searchQuery)
      .then(setSearchResults)
      .catch(() => setSearchResults([]))
      .finally(() => setSearching(false));
  }, [selectedId, searchQuery]);

  if (loading) return <section className="page-frame"><p>{t('knowledge.loading')}</p></section>;

  // ── Wiki tabs ──
  const wikiTabs: Array<{ key: DetailTab; label: string }> = [
    { key: 'pages', label: t('knowledge.tabPages') },
    { key: 'search', label: t('knowledge.tabSearch') },
    { key: 'settings', label: t('knowledge.tabSettings') },
  ];

  return (
    <section className="page-frame">
      <div className="page-header">
        <div>
          <h1>{t('knowledge.title')}</h1>
          <p>{t('knowledge.subtitle')}</p>
        </div>
        <div className="header-actions-right">
          <span className="token-pill">{items.length} {isWiki ? 'bases' : 'bases'}</span>
          <button type="button" className="primary-button" onClick={() => setShowCreate(true)}>
            + Create
          </button>
        </div>
      </div>

      <div className="knowledge-layout">
        {/* ── Sidebar: KB list ── */}
        <div className="knowledge-sidebar">
          {items.map((kb) => (
            <div key={kb.id} className={`knowledge-item ${selectedId === kb.id ? 'active' : ''}`}>
              <button type="button" className="knowledge-item-btn" onClick={() => setSelectedId(kb.id)}>
                <span className="knowledge-item-name">
                  {kb.wiki_mode ? '📖 ' : ''}{kb.name || kb.id}
                </span>
                <span className="knowledge-item-meta">
                  {kb.wiki_mode ? 'Wiki' : 'Vector'} · {(kb.paths ?? []).length} paths
                </span>
              </button>
              <button
                type="button"
                className={`knowledge-item-del ${deleteTarget === kb.id ? 'confirm' : ''}`}
                onClick={(e) => {
                  e.stopPropagation();
                  if (deleteTarget === kb.id) {
                    void handleDelete(kb.id);
                  } else {
                    setDeleteTarget(kb.id);
                  }
                }}
                onBlur={() => setDeleteTarget(null)}
              >
                {deleteTarget === kb.id ? 'Del?' : 'x'}
              </button>
            </div>
          ))}
          {items.length === 0 && <p className="knowledge-empty">{t('knowledge.empty')}</p>}
        </div>

        {/* ── Detail panel ── */}
        {selected && (
          <div className="knowledge-detail">
            {/* ── Wiki mode tabs ── */}
            {isWiki && (
              <div className="wiki-tabs">
                {wikiTabs.map((tab) => (
                  <button
                    key={tab.key}
                    type="button"
                    className={`wiki-tab ${detailTab === tab.key ? 'active' : ''}`}
                    onClick={() => setDetailTab(tab.key)}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>
            )}

            {/* ── Tab: Settings ── */}
            {((!isWiki) || detailTab === 'settings') && (
              <div className="settings-section wiki-settings-scroll">
                <h3 className="settings-section-title">{t('knowledge.name')}</h3>
                <input
                  className="settings-input"
                  value={name}
                  onChange={(e) => { setName(e.target.value); markDirty(); }}
                />

                <h3 className="settings-section-title" style={{ marginTop: '1rem' }}>{t('knowledge.description')}</h3>
                <textarea
                  className="settings-textarea"
                  rows={2}
                  value={description}
                  onChange={(e) => { setDescription(e.target.value); markDirty(); }}
                  placeholder={t('knowledge.descriptionHint')}
                />

                <h3 className="settings-section-title" style={{ marginTop: '1rem' }}>{t('knowledge.wikiMode')}</h3>
                <label className="settings-label" style={{ flexDirection: 'row', alignItems: 'center', gap: '8px' }}>
                  <input
                    type="checkbox"
                    checked={wikiMode}
                    onChange={() => { setWikiMode(!wikiMode); markDirty(); }}
                  />
                  <span>{t('knowledge.wikiModeHint')}</span>
                </label>

                {wikiMode && (
                  <>
                    <h3 className="settings-section-title settings-title-with-tip" style={{ marginTop: '1rem' }}>
                      {t('knowledge.purpose')}
                      <span className="settings-title-tip-icon" data-tip={t('knowledge.purposeHint')}>?</span>
                    </h3>
                    <textarea
                      className="settings-textarea"
                      rows={4}
                      value={purpose}
                      onChange={(e) => { setPurpose(e.target.value); markDirty(); }}
                      placeholder={t('knowledge.purposePlaceholder')}
                    />

                    <h3 className="settings-section-title" style={{ marginTop: '1rem' }}>{t('knowledge.autoSync')}</h3>
                    <label className="settings-label" style={{ flexDirection: 'row', alignItems: 'center', gap: '8px' }}>
                      <input
                        type="checkbox"
                        checked={autoSync}
                        onChange={() => { setAutoSync(!autoSync); markDirty(); }}
                      />
                      <span>{t('knowledge.autoSyncHint')}</span>
                    </label>

                    <h3 className="settings-section-title" style={{ marginTop: '1rem' }}>{t('knowledge.ingestLanguage')}</h3>
                    <p style={{ fontSize: '12px', color: '#8492aa', margin: '0 0 6px' }}>{t('knowledge.ingestLanguageHint')}</p>
                    <select
                      className="settings-select"
                      value={language}
                      onChange={(e) => { setLanguage(e.target.value); markDirty(); }}
                    >
                      <option value="en">English</option>
                      <option value="zh">中文</option>
                    </select>
                  </>
                )}

                <h3 className="settings-section-title" style={{ marginTop: '1rem' }}>{t('knowledge.paths')}</h3>
                <textarea
                  className="settings-textarea"
                  rows={3}
                  value={paths}
                  onChange={(e) => { setPaths(e.target.value); markDirty(); }}
                  placeholder={'D:/projects/api-docs\nE:/技术报告/2025\nC:/work/README.md'}
                />

                <div className="settings-footer" style={{ borderTop: '1px solid rgba(132,146,170,0.1)', marginTop: '1rem' }}>
                  {dirty && <span className="settings-dirty">{t('knowledge.unsavedChanges')}</span>}
                  {!isWiki && (
                    <button type="button" className="secondary-button" onClick={() => handleReload(selected.id)}>
                      Reload
                    </button>
                  )}
                  <button
                    type="button"
                    className="primary-button"
                    disabled={saving || !dirty}
                    onClick={handleSave}
                  >
                    {saving ? 'Saving...' : t('common.save')}
                  </button>
                </div>
              </div>
            )}

            {/* ── Tab: Wiki Pages ── */}
            {isWiki && detailTab === 'pages' && (
              <div className="wiki-pages-panel">
                {/* Toolbar */}
                <div className="wiki-pages-toolbar">
                  <input
                    className="settings-input wiki-filter-input"
                    placeholder="Filter..."
                    value={pageFilter}
                    onChange={(e) => setPageFilter(e.target.value)}
                  />
                  <select className="settings-select" value={pageType} onChange={(e) => setPageType(e.target.value)}>
                    <option value="">All</option>
                    <option value="entities">Entities</option>
                    <option value="concepts">Concepts</option>
                    <option value="sources">Sources</option>
                    <option value="queries">Queries</option>
                  </select>
                  <select
                    className="settings-select"
                    value={language}
                    onChange={(e) => setLanguage(e.target.value)}
                    title={t('knowledge.ingestLanguageHint')}
                  >
                    <option value="en">EN</option>
                    <option value="zh">中文</option>
                  </select>
                  <button
                    type="button"
                    className={syncing ? 'danger-button' : 'secondary-button'}
                    onClick={handleSync}
                  >
                    {syncing ? t('knowledge.cancelSync') : t('knowledge.sync')}
                  </button>
                  <button
                    type="button"
                    className="primary-button"
                    onClick={() => setShowNewPage(true)}
                  >
                    + {t('knowledge.newPage')}
                  </button>
                  {wikiStats && (
                    <span className="wiki-stats-pill">
                      {wikiStats.total} {t('knowledge.pages')}
                    </span>
                  )}
                </div>

                {/* Page list + content */}
                <div className="wiki-pages-content">
                  <div className="wiki-page-list">
                    {wikiPages.map((p) => (
                      <div
                        key={p.path}
                        className={`wiki-page-item ${selectedPagePath === p.path ? 'active' : ''}`}
                        onClick={() => setSelectedPagePath(p.path)}
                      >
                        <span className="wiki-page-item-title">{p.title || p.path.split('/').pop()}</span>
                        <span className="wiki-page-item-meta">
                          <span className="wiki-type-badge">{p.type || '—'}</span>
                          <span className="wiki-page-item-cat">{p.category}</span>
                        </span>
                        <button
                          type="button"
                          className="wiki-page-del-btn"
                          onClick={(e) => { e.stopPropagation(); handleDeletePage(p.path); }}
                          title={t('knowledge.deletePage')}
                        >
                          ×
                        </button>
                      </div>
                    ))}
                    {wikiPages.length === 0 && (
                      <p className="knowledge-empty">{t('knowledge.noWikiPages')}</p>
                    )}
                  </div>

                  {/* Page viewer / editor */}
                  <div className="wiki-page-viewer">
                    {pageContent && !editingPage && (
                      <>
                        <div className="wiki-page-header">
                          <h3>{pageContent.title || pageContent.path.split('/').pop()}</h3>
                          <div className="wiki-page-actions">
                            <button type="button" className="secondary-button" onClick={() => setEditingPage(true)}>
                              {t('knowledge.editPage')}
                            </button>
                          </div>
                        </div>
                        <div className="wiki-page-meta-row">
                          {Object.entries(pageContent.meta).map(([k, v]) => (
                            k !== 'title' ? (
                              <span key={k} className="wiki-meta-tag">
                                <strong>{k}:</strong> {Array.isArray(v) ? v.join(', ') : String(v)}
                              </span>
                            ) : null
                          ))}
                        </div>
                        <div className="wiki-page-body">
                          <MarkdownContent content={pageContent.body} />
                        </div>
                      </>
                    )}
                    {pageContent && editingPage && (
                      <>
                        <div className="wiki-page-header">
                          <h3>Edit: {pageContent.title || pageContent.path.split('/').pop()}</h3>
                          <div className="wiki-page-actions">
                            <button type="button" className="secondary-button" onClick={() => setEditingPage(false)}>
                              {t('knowledge.cancelEdit')}
                            </button>
                            <button type="button" className="primary-button" onClick={handleSavePage}>
                              {t('knowledge.savePage')}
                            </button>
                          </div>
                        </div>
                        <textarea
                          className="wiki-editor"
                          value={editContent}
                          onChange={(e) => setEditContent(e.target.value)}
                        />
                      </>
                    )}
                    {!pageContent && selectedPagePath === null && (
                      <div className="wiki-page-empty">
                        {wikiStats && (
                          <div className="wiki-stats-grid">
                            <div className="wiki-stat-card">
                              <span className="wiki-stat-value">{wikiStats.total}</span>
                              <span className="wiki-stat-label">{t('knowledge.statsTotal')}</span>
                            </div>
                            {Object.entries(wikiStats.by_type).map(([type, count]) => (
                              <div key={type} className="wiki-stat-card">
                                <span className="wiki-stat-value">{count}</span>
                                <span className="wiki-stat-label">{type}</span>
                              </div>
                            ))}
                          </div>
                        )}
                        {graphData && graphData.nodes.length > 0 && (
                          <div className="wiki-graph-container">
                            <WikiGraphView data={graphData} onPageClick={(path) => setSelectedPagePath(path)} />
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>

                {/* New page dialog */}
                {showNewPage && (
                  <div className="dialog-overlay" onClick={() => setShowNewPage(false)}>
                    <div className="dialog-card" onClick={(e) => e.stopPropagation()}>
                      <div className="dialog-header">
                        <h2>{t('knowledge.newPage')}</h2>
                        <button type="button" className="icon-button" onClick={() => setShowNewPage(false)}>X</button>
                      </div>
                      <input
                        type="text"
                        className="dialog-input"
                        placeholder={t('knowledge.newPagePath')}
                        value={newPagePath}
                        onChange={(e) => setNewPagePath(e.target.value)}
                        onKeyDown={(e) => { if (e.key === 'Enter') handleNewPage(); }}
                      />
                      <div className="dialog-actions">
                        <button type="button" className="secondary-button" onClick={() => setShowNewPage(false)}>{t('knowledge.cancel')}</button>
                        <button type="button" className="primary-button" disabled={!newPagePath.trim()} onClick={handleNewPage}>
                          {t('knowledge.newPage')}
                        </button>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* ── Tab: Search ── */}
            {isWiki && detailTab === 'search' && (
              <div className="wiki-search-panel">
                <div className="wiki-search-bar">
                  <input
                    className="settings-input wiki-search-input"
                    placeholder={t('knowledge.searchPlaceholder')}
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') handleSearch(); }}
                  />
                  <button
                    type="button"
                    className="primary-button"
                    disabled={searching || !searchQuery.trim()}
                    onClick={handleSearch}
                  >
                    {searching ? '...' : t('knowledge.tabSearch')}
                  </button>
                </div>
                {searchResults.length > 0 && (
                  <div className="wiki-search-results">
                    <h4>{t('knowledge.searchResults')} ({searchResults.length})</h4>
                    {searchResults.map((r) => (
                      <div
                        key={r.path}
                        className="wiki-search-item"
                        onClick={() => {
                          setSelectedPagePath(r.path);
                          setDetailTab('pages');
                        }}
                      >
                        <div className="wiki-search-item-title">
                          {r.title_match ? <strong>{r.title}</strong> : r.title}
                          {r.title_match && <span className="wiki-title-badge">Title</span>}
                        </div>
                        <div className="wiki-search-item-path">{r.path}</div>
                        <div className="wiki-search-item-snippet">{r.snippet}</div>
                      </div>
                    ))}
                  </div>
                )}
                {searchResults.length === 0 && searchQuery && !searching && (
                  <p className="knowledge-empty">{t('knowledge.noResults')}</p>
                )}
              </div>
            )}

            {/* ── Non-wiki: original settings ── */}
            {!isWiki && (
              <div className="settings-section">
                {/* (already rendered by the settings tab check above) */}
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── Create KB dialog ── */}
      {showCreate && (
        <div className="dialog-overlay" onClick={() => setShowCreate(false)}>
          <div className="dialog-card" onClick={(e) => e.stopPropagation()}>
            <div className="dialog-header">
              <h2>{t('knowledge.createTitle')}</h2>
              <button type="button" className="icon-button" onClick={() => setShowCreate(false)}>X</button>
            </div>
            <input
              type="text"
              className="dialog-input"
              placeholder={t('knowledge.placeholder')}
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') handleCreate(); }}
            />
            <div style={{ marginTop: '12px' }}>
              <label className="settings-label" style={{ flexDirection: 'row', alignItems: 'center', gap: '8px' }}>
                <input
                  type="checkbox"
                  checked={newWikiMode}
                  onChange={() => setNewWikiMode(!newWikiMode)}
                />
                <span>{t('knowledge.wikiMode')}</span>
                <span style={{ color: '#8492aa', fontSize: '12px' }}>({t('knowledge.wikiModeHint')})</span>
              </label>
            </div>
            <div className="dialog-actions">
              <button type="button" className="secondary-button" onClick={() => setShowCreate(false)}>{t('knowledge.cancel')}</button>
              <button
                type="button"
                className="primary-button"
                disabled={!newName.trim()}
                onClick={() => handleCreate()}
              >
                Create
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
