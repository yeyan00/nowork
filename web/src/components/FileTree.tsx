import { useCallback, useEffect, useRef, useState } from 'react';
import { useI18n } from '../i18n';
import { listDirectory, type DirListResult } from '../lib/filePreview';
import type { FileNode, WorkspaceInfo } from '../types';

interface FileTreeProps {
  workspace: WorkspaceInfo | null;
  onFileSelect: (node: FileNode) => void;
  selectedFilePath: string | null;
}

/**
 * Lazy-loaded file tree for a single workspace.
 * Uses a flat Map<dirPath, FileNode[]> cache for efficient incremental refresh.
 */
export function FileTree({ workspace, onFileSelect, selectedFilePath }: FileTreeProps) {
  const { t } = useI18n();
  const [childrenByDir, setChildrenByDir] = useState<Record<string, FileNode[]>>({});
  const [expandedDirs, setExpandedDirs] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const loadedDirsRef = useRef<Set<string>>(new Set());
  const inFlightRef = useRef<Set<string>>(new Set());
  // Track the current workspace path in a ref so async callbacks always read the latest
  const workspacePathRef = useRef<string | null>(null);

  // Keep ref in sync
  workspacePathRef.current = workspace?.path ?? null;

  const loadDir = useCallback(async (dirPath: string) => {
    if (loadedDirsRef.current.has(dirPath) || inFlightRef.current.has(dirPath)) return;

    inFlightRef.current = new Set(inFlightRef.current);
    inFlightRef.current.add(dirPath);

    // Show loading indicator for the root directory
    const isRoot = dirPath === workspacePathRef.current;
    if (isRoot) setLoading(true);

    try {
      const result: DirListResult = await listDirectory(dirPath);

      // Only apply if this directory is still relevant (workspace may have changed during fetch)
      loadedDirsRef.current = new Set(loadedDirsRef.current);
      loadedDirsRef.current.add(dirPath);
      setChildrenByDir(prev => ({ ...prev, [dirPath]: result.entries }));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load directory');
    } finally {
      inFlightRef.current = new Set(inFlightRef.current);
      inFlightRef.current.delete(dirPath);
      if (isRoot) setLoading(false);
    }
  }, []); // No deps — uses ref for workspace path, so closure is stable

  // Reset + load root when workspace changes
  useEffect(() => {
    const path = workspace?.path;
    if (!path) return;

    // Full reset
    setChildrenByDir({});
    setExpandedDirs(new Set());
    loadedDirsRef.current = new Set();
    inFlightRef.current = new Set();
    setError(null);
    setSearchQuery('');
    setLoading(true);

    void loadDir(path);
  }, [workspace?.path, loadDir]);

  const toggleDir = useCallback((dirPath: string) => {
    setExpandedDirs(prev => {
      const next = new Set(prev);
      if (next.has(dirPath)) {
        next.delete(dirPath);
      } else {
        next.add(dirPath);
        if (!loadedDirsRef.current.has(dirPath)) {
          void loadDir(dirPath);
        }
      }
      return next;
    });
  }, [loadDir]);

  const handleRefresh = useCallback(() => {
    const path = workspace?.path;
    if (!path) return;
    loadedDirsRef.current = new Set();
    inFlightRef.current = new Set();
    setChildrenByDir({});
    setLoading(true);
    void loadDir(path);
  }, [loadDir, workspace?.path]);

  // Search: recursively walk cached dirs to find matching files
  const allFiles = useCallback((): FileNode[] => {
    const rootPath = workspace?.path;
    if (!rootPath) return [];
    const result: FileNode[] = [];
    const walk = (dirPath: string) => {
      const children = childrenByDir[dirPath];
      if (!children) return;
      for (const child of children) {
        if (child.isFile) result.push(child);
        if (child.isDirectory) walk(child.path);
      }
    };
    walk(rootPath);
    return result;
  }, [childrenByDir, workspace?.path]);

  const filteredFiles = searchQuery.trim()
    ? allFiles().filter(f => f.name.toLowerCase().includes(searchQuery.toLowerCase()))
    : null;

  function renderNode(node: FileNode, depth: number): React.ReactNode {
    const isDir = node.isDirectory;
    const isExpanded = expandedDirs.has(node.path);
    const isSelected = node.path === selectedFilePath;

    return (
      <li key={node.path} className="file-tree-node">
        <button
          type="button"
          className={`file-tree-row ${isSelected ? 'selected' : ''}`}
          style={{ paddingLeft: `${8 + depth * 14}px` }}
          onClick={() => isDir ? toggleDir(node.path) : onFileSelect(node)}
          title={node.path}
        >
          <span className={`file-tree-icon ${isDir ? (isExpanded ? 'dir-open' : 'dir') : 'file'}`}>
            {isDir ? (isExpanded ? '📂' : '📁') : getFileEmoji(node.name)}
          </span>
          <span className="file-tree-name">{node.name}</span>
        </button>
        {isDir && isExpanded && (
          <ul className="file-tree-children">
            {(childrenByDir[node.path] ?? []).map(child => renderNode(child, depth + 1))}
          </ul>
        )}
      </li>
    );
  }

  const rootPath = workspace?.path;
  const rootChildren = rootPath ? (childrenByDir[rootPath] ?? []) : [];
  const isEmpty = !loading && !error && rootChildren.length === 0;

  return (
    <div className="file-tree-panel">
      <div className="file-tree-toolbar">
        <div className="file-tree-search">
          <input
            type="text"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            placeholder={t('filePreview.searchFiles') || 'Search files…'}
            className="file-tree-search-input"
          />
          {searchQuery && (
            <button
              type="button"
              className="file-tree-search-clear"
              onClick={() => setSearchQuery('')}
              aria-label="Clear"
            >
              ✕
            </button>
          )}
        </div>
        <button
          type="button"
          className="file-tree-refresh-btn"
          onClick={handleRefresh}
          title={t('filePreview.refresh') || 'Refresh'}
          aria-label="Refresh"
        >
          🔄
        </button>
      </div>

      <div className="file-tree-content">
        {error && <div className="file-tree-error">{error}</div>}

        {loading && rootChildren.length === 0 ? (
          <div className="file-tree-loading">
            <span className="preview-spinner" /> {t('filePreview.loading') || 'Loading…'}
          </div>
        ) : filteredFiles ? (
          <ul className="file-tree-list">
            {filteredFiles.length === 0 ? (
              <li className="file-tree-empty">{t('filePreview.noResults') || 'No results'}</li>
            ) : (
              filteredFiles.map(f => renderNode(f, 0))
            )}
          </ul>
        ) : isEmpty ? (
          <div className="file-tree-empty">
            {rootPath
              ? (t('filePreview.emptyDirectory') || 'This directory is empty')
              : (t('filePreview.noWorkspaces') || 'No workspace selected')
            }
          </div>
        ) : (
          <ul className="file-tree-list">
            {rootChildren.map(child => renderNode(child, 0))}
          </ul>
        )}
      </div>
    </div>
  );
}

function getFileEmoji(name: string): string {
  const ext = name.split('.').pop()?.toLowerCase() || '';
  const map: Record<string, string> = {
    md: '📝', markdown: '📝',
    json: '📋', jsonc: '📋', json5: '📋',
    py: '🐍', js: '📜', ts: '🔷', tsx: '⚛️', jsx: '⚛️',
    html: '🌐', css: '🎨', scss: '🎨',
    png: '🖼️', jpg: '🖼️', jpeg: '🖼️', gif: '🖼️', svg: '🖼️', webp: '🖼️',
    sql: '🗃️', sh: '⚙️', bash: '⚙️',
    yaml: '⚙️', yml: '⚙️', toml: '⚙️',
    txt: '📄', log: '📄', env: '🔒',
    lock: '🔒', gitignore: '👁️',
  };
  return map[ext] || '📄';
}
