/**
 * File system API and state management for file preview sidebar.
 */

import type { FileNode } from '../types';
import { fetchFromApi } from './backend';

// ── API ─────────────────────────────────────────────────────────

export interface DirListResult {
  path: string;
  entries: FileNode[];
}

export async function listDirectory(dirPath: string, showHidden = false): Promise<DirListResult> {
  const params = new URLSearchParams({ path: dirPath, showHidden: String(showHidden) });
  const response = await fetchFromApi(`/api/fs/list?${params}`);
  if (!response.ok) throw new Error('Failed to list directory');
  return (await response.json()) as DirListResult;
}

export interface FileReadResult {
  path: string;
  content: string;
  size: number;
  encoding: string;
}

export async function readFile(filePath: string, encoding = 'utf-8'): Promise<FileReadResult> {
  const params = new URLSearchParams({ path: filePath, encoding });
  const response = await fetchFromApi(`/api/fs/read?${params}`);
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error((detail as { detail?: string }).detail || 'Failed to read file');
  }
  return (await response.json()) as FileReadResult;
}

export interface RawFileResult {
  path: string;
  dataUrl: string;
  size: number;
  mimeType: string | null;
}

export async function readRawFile(filePath: string): Promise<RawFileResult> {
  const params = new URLSearchParams({ path: filePath });
  const response = await fetchFromApi(`/api/fs/raw?${params}`);
  if (!response.ok) throw new Error('Failed to read raw file');
  return (await response.json()) as RawFileResult;
}

export interface FileStatResult {
  name: string;
  path: string;
  isDirectory: boolean;
  isFile: boolean;
  size: number;
  mtimeMs: number;
}

export async function statFile(filePath: string): Promise<FileStatResult> {
  const params = new URLSearchParams({ path: filePath });
  const response = await fetchFromApi(`/api/fs/stat?${params}`);
  if (!response.ok) throw new Error('Failed to stat file');
  return (await response.json()) as FileStatResult;
}

// ── File Type Helpers ───────────────────────────────────────────

export type FileCategory = 'image' | 'markdown' | 'json' | 'html' | 'style' | 'code';

const IMAGE_EXTENSIONS = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'ico', 'bmp', 'avif']);
const MARKDOWN_EXTENSIONS = new Set(['md', 'markdown']);
const JSON_EXTENSIONS = new Set(['json', 'jsonc', 'json5', 'geojson']);
const HTML_EXTENSIONS = new Set(['html', 'htm']);
const STYLE_EXTENSIONS = new Set(['css', 'scss', 'sass', 'less']);

export function getFileCategory(filePath: string): FileCategory {
  const ext = filePath.split('.').pop()?.toLowerCase() || '';
  if (IMAGE_EXTENSIONS.has(ext)) return 'image';
  if (MARKDOWN_EXTENSIONS.has(ext)) return 'markdown';
  if (JSON_EXTENSIONS.has(ext)) return 'json';
  if (HTML_EXTENSIONS.has(ext)) return 'html';
  if (STYLE_EXTENSIONS.has(ext)) return 'style';
  return 'code';
}

export function getFileName(filePath: string): string {
  return filePath.replace(/\\/g, '/').split('/').filter(Boolean).pop() || filePath;
}

export function getFileExtension(filePath: string): string | undefined {
  const name = getFileName(filePath);
  const dotIdx = name.lastIndexOf('.');
  if (dotIdx <= 0) return undefined;
  return name.slice(dotIdx + 1).toLowerCase();
}

export function getRelativePath(filePath: string, rootPath: string): string {
  const normalizedFile = filePath.replace(/\\/g, '/');
  const normalizedRoot = rootPath.replace(/\\/g, '/').replace(/\/+$/, '');
  if (normalizedFile.startsWith(normalizedRoot + '/')) {
    return normalizedFile.slice(normalizedRoot.length + 1);
  }
  return normalizedFile;
}

export function isImageFile(filePath: string): boolean {
  return getFileCategory(filePath) === 'image';
}

/**
 * Get a preview snippet of file content (first N lines).
 */
export function getPreviewSnippet(content: string, maxLines = 8, maxLineLen = 120): string {
  if (!content) return '';
  const lines = content.split('\n').slice(0, maxLines);
  return lines.map(line => line.length > maxLineLen ? line.slice(0, maxLineLen) + '…' : line).join('\n');
}
