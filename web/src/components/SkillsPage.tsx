import { useCallback, useEffect, useState } from 'react';
import { useI18n } from '../i18n';
import { deleteSkill, getSkillFile, installSkill, listSkillFiles, listSkills } from '../lib/backend';
import type { SkillFileNode, SkillSummary } from '../lib/backend';
import { MarkdownContent } from './MarkdownContent';

interface FileTreeNode {
  name: string;
  path: string;
  children: FileTreeNode[];
  isFile: boolean;
}

function buildFileTree(files: SkillFileNode[]): FileTreeNode[] {
  const root: FileTreeNode[] = [];
  for (const f of files) {
    const parts = f.name.split('/');
    let current = root;
    for (let i = 0; i < parts.length; i++) {
      const part = parts[i];
      const isLast = i === parts.length - 1;
      let node = current.find((n) => n.name === part);
      if (!node) {
        node = { name: part, path: parts.slice(0, i + 1).join('/'), children: [], isFile: isLast };
        current.push(node);
      }
      current = node.children;
    }
  }
  return root;
}

function FileTreeItem({ node, activeFile, onSelect }: {
  node: FileTreeNode;
  activeFile: string;
  onSelect: (path: string) => void;
}) {
  const [open, setOpen] = useState(true);
  if (node.isFile) {
    return (
      <button
        type="button"
        className={`tree-file ${activeFile === node.path ? 'active' : ''}`}
        onClick={() => onSelect(node.path)}
      >
        <span className="tree-icon-doc" />
        {node.name}
      </button>
    );
  }
  return (
    <div className="tree-folder">
      <button type="button" className="tree-folder-toggle" onClick={() => setOpen((v) => !v)}>
        <span className={`tree-icon-folder ${open ? 'open' : ''}`}>{open ? '\u25BE' : '\u25B8'}</span>
        {node.name}
      </button>
      {open && node.children.map((child) => (
        <FileTreeItem key={child.path} node={child} activeFile={activeFile} onSelect={onSelect} />
      ))}
    </div>
  );
}

function InstallDialog({ onClose, onInstalled }: { onClose: () => void; onInstalled: () => void }) {
  const { t } = useI18n();
  const [source, setSource] = useState('');
  const [installing, setInstalling] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; msg: string } | null>(null);
  const [duplicateName, setDuplicateName] = useState<string | null>(null);

  const handleInstall = useCallback(async (overwrite = false) => {
    if (!source.trim()) return;
    setInstalling(true);
    setResult(null);
    setDuplicateName(null);
    try {
      const res = await installSkill(source.trim(), overwrite);
      if (res.ok) {
        setResult({ ok: true, msg: `Installed: ${res.name}` });
        onInstalled();
      } else if (res.duplicate) {
        setDuplicateName(res.name || '');
        setResult({ ok: false, msg: res.error || 'Duplicate skill found' });
      } else {
        setResult({ ok: false, msg: res.error || 'Install failed' });
      }
    } catch {
      setResult({ ok: false, msg: 'Request failed' });
    } finally {
      setInstalling(false);
    }
  }, [source, onInstalled]);

  return (
    <div className="dialog-overlay" onClick={onClose}>
      <div className="dialog-card" onClick={(e) => e.stopPropagation()}>
        <div className="dialog-header">
          <h2>{t('skills.installTitle')}</h2>
          <button type="button" className="icon-button" onClick={onClose}>X</button>
        </div>
        <p className="dialog-hint">{t('skills.installHint')}</p>
        <input
          type="text"
          className="dialog-input"
          placeholder="e.g. C:/skills/my-skill or https://example.com/skill.zip"
          value={source}
          onChange={(e) => { setSource(e.target.value); setDuplicateName(null); setResult(null); }}
          onKeyDown={(e) => { if (e.key === 'Enter' && !duplicateName) void handleInstall(); }}
        />
        {result && (
          <p className={result.ok ? 'dialog-success' : 'dialog-error'}>{result.msg}</p>
        )}
        <div className="dialog-actions">
          <button type="button" className="secondary-button" onClick={onClose}>{t('skills.cancel')}</button>
          {duplicateName && (
            <button
              type="button"
              className="danger-button"
              disabled={installing}
              onClick={() => void handleInstall(true)}
            >
              {installing ? 'Overwriting...' : 'Overwrite'}
            </button>
          )}
          <button
            type="button"
            className="primary-button"
            disabled={installing || !source.trim()}
            onClick={() => void handleInstall(false)}
          >
            {installing ? t('skills.installing') : t('skills.install')}
          </button>
        </div>
      </div>
    </div>
  );
}

export function SkillsPage() {
  const { t } = useI18n();
  const [skills, setSkills] = useState<SkillSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedSkill, setSelectedSkill] = useState<SkillSummary | null>(null);
  const [activeFile, setActiveFile] = useState<string>('SKILL.md');
  const [fileContent, setFileContent] = useState<string>('');
  const [fileLoading, setFileLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [fileTree, setFileTree] = useState<FileTreeNode[]>([]);
  const [showInstall, setShowInstall] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  const loadSkills = useCallback(() => {
    setLoading(true);
    setError(null);
    void listSkills()
      .then((s) => { setSkills(s); if (s.length > 0 && !selectedSkill) setSelectedSkill(s[0]); })
      .catch(() => setError('Failed to load skills'))
      .finally(() => setLoading(false));
  }, [selectedSkill]);

  useEffect(() => { loadSkills(); }, []);

  useEffect(() => {
    if (!selectedSkill) return;
    if (!skills.find((s) => s.name === selectedSkill.name)) {
      setSelectedSkill(skills[0] || null);
      return;
    }
    setActiveFile('SKILL.md');
    setFileContent(selectedSkill.instructions);
    void listSkillFiles(selectedSkill.name)
      .then((files) => setFileTree(buildFileTree(files)))
      .catch(() => setFileTree([]));
  }, [selectedSkill, skills]);

  const handleDelete = useCallback(async (skillName: string) => {
    try {
      await deleteSkill(skillName);
      if (selectedSkill?.name === skillName) {
        setSelectedSkill(null);
      }
      loadSkills();
    } catch {
    }
  }, [selectedSkill, loadSkills]);

  const handleFileClick = useCallback(async (skill: SkillSummary, filePath: string) => {
    setActiveFile(filePath);
    setFileLoading(true);
    try {
      const content = await getSkillFile(skill.name, filePath);
      setFileContent(content);
    } catch {
      setFileContent('Failed to load file');
    } finally {
      setFileLoading(false);
    }
  }, []);

  const filteredSkills = searchQuery
    ? skills.filter((s) =>
        s.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        s.description.toLowerCase().includes(searchQuery.toLowerCase()))
    : skills;

  if (loading) return <section className="page-frame"><p>{t('skills.loading')}</p></section>;
  if (error) return <section className="page-frame"><p>{error}</p></section>;

  return (
    <section className="page-frame">
      <div className="page-header">
        <div>
          <h1>{t('skills.title')}</h1>
          <p>{t('skills.subtitle')}</p>
        </div>
        <div className="header-actions-right">
          <span className="token-pill">{skills.length} skills</span>
          <button type="button" className="primary-button" title="Install Skill" onClick={() => setShowInstall(true)}>
            + Install
          </button>
        </div>
      </div>

      <div className="skills-layout">
        <div className="skills-sidebar">
          <input
            type="text"
            className="skill-search"
            placeholder={t('skills.search')}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
          <div className="skills-list">
            {filteredSkills.map((s) => (
              <div key={s.name} className={`skill-item-wrapper ${selectedSkill?.name === s.name ? 'active' : ''}`}>
                <button
                  type="button"
                  className="skill-item"
                  onClick={() => setSelectedSkill(s)}
                >
                  <span className="skill-name">{s.name}</span>
                  <span className="skill-desc">{s.description.slice(0, 80)}{s.description.length > 80 ? '...' : ''}</span>
                </button>
                <button
                  type="button"
                  className={`skill-delete-btn ${deleteTarget === s.name ? 'confirm' : ''}`}
                  title={`Delete ${s.name}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    if (deleteTarget === s.name) {
                      setDeleteTarget(null);
                      void handleDelete(s.name);
                    } else {
                      setDeleteTarget(s.name);
                    }
                  }}
                  onBlur={() => setDeleteTarget(null)}
                >
                  {deleteTarget === s.name ? 'Del?' : 'x'}
                </button>
              </div>
            ))}
            {filteredSkills.length === 0 && <p className="skill-empty">{t('skills.empty')}</p>}
          </div>
        </div>

        {selectedSkill && (
          <div className="skill-detail">
            <div className="skill-detail-sidebar">
              <div className="skill-file-tree">
                {fileTree.map((node) => (
                  <FileTreeItem
                    key={node.path}
                    node={node}
                    activeFile={activeFile}
                    onSelect={(p) => void handleFileClick(selectedSkill, p)}
                  />
                ))}
              </div>
            </div>
            <div className="skill-detail-content">
              {fileLoading ? (
                <p>{t('skills.loadMore')}</p>
              ) : activeFile === 'SKILL.md' || activeFile.endsWith('.md') ? (
                <MarkdownContent content={fileContent} />
              ) : (
                <pre className="skill-raw">{fileContent}</pre>
              )}
            </div>
          </div>
        )}
      </div>

      {showInstall && (
        <InstallDialog onClose={() => setShowInstall(false)} onInstalled={loadSkills} />
      )}
    </section>
  );
}
