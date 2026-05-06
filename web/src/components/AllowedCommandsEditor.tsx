import { useCallback, useMemo, useState } from 'react';
import { useI18n } from '../i18n';

/**
 * Default allowed commands grouped by category.
 * Matches the backend CodingTools._BASH_COMMANDS and _POWERSHELL_COMMANDS.
 */
const DEFAULT_COMMANDS_BY_CATEGORY: Record<string, string[]> = {
  Python: ['python', 'python3', 'pip', 'pip3', 'uv', 'poetry', 'pipx', 'pytest', 'unittest', 'black', 'ruff', 'mypy', 'pylint', 'flake8'],
  NodeJS: ['node', 'npm', 'npx', 'yarn', 'pnpm', 'bun', 'deno', 'tsc', 'tsx', 'eslint', 'prettier', 'vite', 'vitest', 'jest'],
  Build: ['make', 'cmake', 'gcc', 'g++', 'clang', 'clang++', 'cargo', 'rustc', 'rustup', 'go'],
  Git: ['git', 'gh'],
  Search: ['grep', 'rg', 'fd', 'find', 'sed', 'awk', 'tr', 'cut', 'sort', 'uniq', 'diff', 'patch', 'xargs', 'wc'],
  File: ['ls', 'cat', 'head', 'tail', 'tee', 'mkdir', 'rm', 'mv', 'cp', 'touch', 'ln', 'basename', 'dirname', 'realpath', 'readlink', 'file', 'stat'],
  Archive: ['tar', 'zip', 'unzip', 'gzip', 'gunzip'],
  Network: ['curl', 'wget'],
  System: ['pwd', 'which', 'whoami', 'hostname', 'uname', 'date', 'env', 'printenv', 'echo', 'printf', 'ps', 'df', 'du', 'timeout', 'kill'],
  Database: ['sqlite3', 'psql', 'mysql', 'redis-cli'],
  Container: ['docker'],
  Other: ['ruby', 'java', 'dotnet', 'browser-use'],
};

/** All default commands as a flat set */
const ALL_DEFAULT_COMMANDS = new Set(
  Object.values(DEFAULT_COMMANDS_BY_CATEGORY).flat()
);

interface AllowedCommandsEditorProps {
  /** Current allowed commands (empty array = use defaults) */
  commands: string[];
  /** Update commands callback */
  onChange: (commands: string[]) => void;
  /** Mark dirty callback */
  onDirty: () => void;
}

/**
 * Editor for CodingTools allowed_commands configuration.
 * 
 * Displays default commands grouped by category with toggle switches.
 * Custom commands can be added and removed.
 */
export function AllowedCommandsEditor({ commands, onChange, onDirty }: AllowedCommandsEditorProps) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState(false);
  const [newCommand, setNewCommand] = useState('');

  // Parse commands into default (toggled) and custom (added)
  const { enabledDefaults, customCommands } = useMemo(() => {
    const enabled: Set<string> = new Set();
    const custom: string[] = [];
    for (const cmd of commands) {
      if (ALL_DEFAULT_COMMANDS.has(cmd)) {
        enabled.add(cmd);
      } else {
        custom.push(cmd);
      }
    }
    return { enabledDefaults: enabled, customCommands: custom };
  }, [commands]);

  // Use defaults when commands array is empty
  const useDefaults = commands.length === 0;

  const toggleDefaultCommand = useCallback((cmd: string) => {
    const newCommands = [...commands];
    const idx = newCommands.indexOf(cmd);
    if (idx >= 0) {
      newCommands.splice(idx, 1);
    } else {
      newCommands.push(cmd);
    }
    onChange(newCommands);
    onDirty();
  }, [commands, onChange, onDirty]);

  const addCustomCommand = useCallback(() => {
    const input = newCommand.trim();
    if (!input) return;
    
    // Parse comma-separated input
    const toAdd = input.split(',').map(s => s.trim()).filter(s => s && !commands.includes(s));
    if (toAdd.length === 0) return;
    
    onChange([...commands, ...toAdd]);
    setNewCommand('');
    onDirty();
  }, [commands, newCommand, onChange, onDirty]);

  const removeCustomCommand = useCallback((cmd: string) => {
    onChange(commands.filter(c => c !== cmd));
    onDirty();
  }, [commands, onChange, onDirty]);

  const resetToDefaults = useCallback(() => {
    onChange([]);
    onDirty();
  }, [onChange, onDirty]);

  const toggleCategory = useCallback((category: string, enable: boolean) => {
    const catCommands = DEFAULT_COMMANDS_BY_CATEGORY[category] ?? [];
    let newCommands = [...commands];
    
    if (enable) {
      // Add all commands from this category that aren't already in the list
      for (const cmd of catCommands) {
        if (!newCommands.includes(cmd)) {
          newCommands.push(cmd);
        }
      }
    } else {
      // Remove all commands from this category
      newCommands = newCommands.filter(c => !catCommands.includes(c));
    }
    
    onChange(newCommands);
    onDirty();
  }, [commands, onChange, onDirty]);

  // Count summary
  const defaultCount = useDefaults ? ALL_DEFAULT_COMMANDS.size : enabledDefaults.size;
  const totalCount = useDefaults ? ALL_DEFAULT_COMMANDS.size : commands.length;
  const summary = useDefaults
    ? `${totalCount} ${t('workerSettings.defaultCommands') || 'default'}`
    : `${totalCount} (${defaultCount} ${t('workerSettings.default') || 'default'} + ${customCommands.length} ${t('workerSettings.custom') || 'custom'})`;

  return (
    <div className="allowed-commands-editor">
      <button
        type="button"
        className="allowed-commands-header"
        onClick={() => setExpanded(v => !v)}
      >
        <span className="allowed-commands-icon">{expanded ? '▾' : '▸'}</span>
        <span className="allowed-commands-title">
          {t('workerSettings.allowedCommands') || 'Allowed Commands'}
        </span>
        <span className="allowed-commands-summary">{summary}</span>
      </button>

      {expanded && (
        <div className="allowed-commands-body">
          {/* Reset button */}
          <div className="allowed-commands-reset-row">
            <button
              type="button"
              className="allowed-commands-reset-btn"
              onClick={resetToDefaults}
              disabled={useDefaults}
            >
              {t('workerSettings.resetToDefaults') || 'Reset to Defaults'}
            </button>
            {!useDefaults && (
              <span className="allowed-commands-reset-hint">
                {t('workerSettings.resetHint') || 'Empty list = use all defaults'}
              </span>
            )}
          </div>

          {/* Default commands by category */}
          {Object.entries(DEFAULT_COMMANDS_BY_CATEGORY).map(([category, catCommands]) => {
            const enabledInCat = catCommands.filter(cmd => 
              useDefaults || enabledDefaults.has(cmd)
            ).length;
            const allEnabled = enabledInCat === catCommands.length;
            const noneEnabled = enabledInCat === 0 && !useDefaults;

            return (
              <div key={category} className="allowed-commands-category">
                <div className="allowed-commands-category-header">
                  <button
                    type="button"
                    className="allowed-commands-category-toggle"
                    onClick={() => toggleCategory(category, !allEnabled)}
                    title={allEnabled ? 'Disable all' : 'Enable all'}
                  >
                    {allEnabled || useDefaults ? '✓' : noneEnabled ? '○' : '◐'}
                  </button>
                  <span className="allowed-commands-category-name">{category}</span>
                  <span className="allowed-commands-category-count">
                    {useDefaults ? catCommands.length : enabledInCat}/{catCommands.length}
                  </span>
                </div>
                <div className="allowed-commands-category-items">
                  {catCommands.map(cmd => {
                    const enabled = useDefaults || enabledDefaults.has(cmd);
                    return (
                      <button
                        key={cmd}
                        type="button"
                        className={`allowed-commands-item ${enabled ? 'enabled' : 'disabled'}`}
                        onClick={() => toggleDefaultCommand(cmd)}
                        title={cmd}
                      >
                        <span className="allowed-commands-item-check">
                          {enabled ? '✓' : ''}
                        </span>
                        <span className="allowed-commands-item-name">{cmd}</span>
                      </button>
                    );
                  })}
                </div>
              </div>
            );
          })}

          {/* Custom commands */}
          {customCommands.length > 0 && (
            <div className="allowed-commands-custom">
              <div className="allowed-commands-custom-header">
                <span className="allowed-commands-custom-label">
                  {t('workerSettings.customCommands') || 'Custom Commands'}
                </span>
              </div>
              <div className="allowed-commands-custom-items">
                {customCommands.map(cmd => (
                  <span key={cmd} className="allowed-commands-custom-tag">
                    {cmd}
                    <button
                      type="button"
                      className="allowed-commands-custom-remove"
                      onClick={() => removeCustomCommand(cmd)}
                      title={t('workerSettings.remove') || 'Remove'}
                    >
                      ✕
                    </button>
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Add custom command */}
          <div className="allowed-commands-add-row">
            <input
              type="text"
              className="allowed-commands-add-input"
              value={newCommand}
              onChange={e => setNewCommand(e.target.value)}
              placeholder={t('workerSettings.addCommandPlaceholder') || 'npm, docker, ...'}
              onKeyDown={e => { if (e.key === 'Enter') addCustomCommand(); }}
            />
            <button
              type="button"
              className="allowed-commands-add-btn"
              onClick={addCustomCommand}
              disabled={!newCommand.trim()}
            >
              {t('workerSettings.add') || 'Add'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}