import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useI18n } from '../i18n';
import { FileTree } from './FileTree';
import { PreviewPanel } from './PreviewPanel';
import { WorkspaceSelector } from './WorkspaceSelector';
import { getFileCategory } from '../lib/filePreview';
import type { FileNode, PreviewingFile, WorkspaceInfo } from '../types';

interface FilePreviewSidebarProps {
  /** Whether the sidebar is visible */
  open: boolean;
  /** Toggle sidebar visibility */
  onToggle: () => void;
  /** Available workspaces from worker config */
  workspaces: WorkspaceInfo[];
  /** The file to preview (set externally, e.g. from chat FileCard click) */
  externalPreviewFile: PreviewingFile | null;
  /** Clear external preview request */
  onExternalPreviewHandled: () => void;
}

/**
 * File preview sidebar — overlay + slide-in from the right.
 * Same pattern as HelpPanel / WorkerSettingsSidebar.
 */
export function FilePreviewSidebar({
  open,
  onToggle,
  workspaces,
  externalPreviewFile,
  onExternalPreviewHandled,
}: FilePreviewSidebarProps) {
  const { t } = useI18n();
  const [currentWorkspacePath, setCurrentWorkspacePath] = useState<string | null>(null);
  const [previewingFile, setPreviewingFile] = useState<PreviewingFile | null>(null);
  const [treeCollapsed, setTreeCollapsed] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(480);
  const draggingRef = useRef(false);
  const startXRef = useRef(0);
  const startWidthRef = useRef(0);

  const currentWorkspace = useMemo(
    () => workspaces.find(ws => ws.path === currentWorkspacePath) ?? null,
    [workspaces, currentWorkspacePath],
  );

  // Initialize workspace from the first available
  useEffect(() => {
    if (workspaces.length > 0 && !currentWorkspacePath) {
      setCurrentWorkspacePath(workspaces[0].path);
    }
  }, [workspaces, currentWorkspacePath]);

  // Handle external preview requests (from FileCard clicks)
  useEffect(() => {
    if (!externalPreviewFile) return;
    if (externalPreviewFile.workspacePath && externalPreviewFile.workspacePath !== currentWorkspacePath) {
      setCurrentWorkspacePath(externalPreviewFile.workspacePath);
    }
    setPreviewingFile(externalPreviewFile);
    onExternalPreviewHandled();
  }, [externalPreviewFile, currentWorkspacePath, onExternalPreviewHandled]);

  const handleFileSelect = useCallback((node: FileNode) => {
    setPreviewingFile({
      workspacePath: currentWorkspacePath || '',
      path: node.path,
      name: node.name,
      extension: node.name.includes('.') ? node.name.split('.').pop()?.toLowerCase() : undefined,
      content: '',
      category: getFileCategory(node.path),
      source: 'tree',
    });
  }, [currentWorkspacePath]);

  const handleWorkspaceSwitch = useCallback((path: string) => {
    setCurrentWorkspacePath(path);
    setPreviewingFile(null);
    setTreeCollapsed(false);
  }, []);

  const handleClosePreview = useCallback(() => {
    setPreviewingFile(null);
  }, []);

  const handleClose = useCallback(() => {
    onToggle();
  }, [onToggle]);

  // Drag-to-resize (drag left edge)
  const handleDividerDown = useCallback((e: React.PointerEvent) => {
    draggingRef.current = true;
    startXRef.current = e.clientX;
    startWidthRef.current = sidebarWidth;
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
  }, [sidebarWidth]);

  const handleDividerMove = useCallback((e: React.PointerEvent) => {
    if (!draggingRef.current) return;
    const delta = startXRef.current - e.clientX; // drag left = wider
    const next = Math.min(700, Math.max(300, startWidthRef.current + delta));
    setSidebarWidth(next);
  }, []);

  const handleDividerUp = useCallback(() => {
    draggingRef.current = false;
  }, []);

  if (!open) return null;

  return (
    <div className="fp-overlay" onClick={(e) => { if (e.target === e.currentTarget) handleClose(); }}>
      <aside className="fp-sidebar" style={{ width: `min(${sidebarWidth}px, 90%)` }}>
        {/* Drag handle on left edge */}
        <div
          className="fp-resizer"
          onPointerDown={handleDividerDown}
          onPointerMove={handleDividerMove}
          onPointerUp={handleDividerUp}
        />

        {/* Header */}
        <div className="fp-header">
          <div className="fp-header-title">
            <svg viewBox="0 0 20 20" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M3 4h5l2 2h7v10H3V4z" />
              <path d="M3 8h14" />
            </svg>
            <h3>{t('filePreview.files')}</h3>
          </div>
          <button type="button" className="icon-button fp-close" onClick={handleClose} aria-label="Close">
            <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><line x1="5" y1="5" x2="15" y2="15" /><line x1="15" y1="5" x2="5" y2="15" /></svg>
          </button>
        </div>

        {/* Workspace Selector */}
        <WorkspaceSelector
          workspaces={workspaces}
          currentPath={currentWorkspacePath}
          onSwitch={handleWorkspaceSwitch}
        />

        {/* Main content: tree + preview */}
        <div className="fp-body">
          {!treeCollapsed && (
            <div className="fp-tree-section">
              <div className="fp-tree-header">
                <span>{t('filePreview.fileTree')}</span>
                {previewingFile && (
                  <button
                    type="button"
                    className="fp-tree-collapse-btn"
                    onClick={() => setTreeCollapsed(true)}
                    title={t('filePreview.collapseTree')}
                  >
                    ◀
                  </button>
                )}
              </div>
              <FileTree
                workspace={currentWorkspace}
                onFileSelect={handleFileSelect}
                selectedFilePath={previewingFile?.path ?? null}
              />
            </div>
          )}

          <div className="fp-preview-section">
            {treeCollapsed && (
              <button
                type="button"
                className="fp-tree-expand-btn"
                onClick={() => setTreeCollapsed(false)}
                title={t('filePreview.expandTree')}
              >
                ▶ {t('filePreview.files')}
              </button>
            )}
            <PreviewPanel
              file={previewingFile}
              workspace={currentWorkspace}
              onClose={handleClosePreview}
            />
          </div>
        </div>
      </aside>
    </div>
  );
}
