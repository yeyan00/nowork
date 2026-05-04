import { useEffect, useMemo, useState } from 'react';
import { marked } from 'marked';
import { readRawFile } from '../lib/filePreview';

marked.setOptions({ breaks: true, gfm: true });

interface MarkdownContentProps {
  content: string;
  /** Base directory path for resolving relative image URLs */
  basePath?: string;
}

/**
 * Renders markdown content with relative image path resolution.
 * Images with relative URLs are fetched via the backend and converted to data URLs.
 */
export function MarkdownContent({ content, basePath }: MarkdownContentProps) {
  const [resolvedHtml, setResolvedHtml] = useState('');
  const initialHtml = useMemo(() => {
    if (!content) return '';
    return marked.parse(content, { async: false }) as string;
  }, [content]);

  // Resolve relative image URLs
  useEffect(() => {
    if (!content || !basePath) {
      setResolvedHtml(initialHtml);
      return;
    }

    // Find all relative image URLs in the HTML
    const imgRegex = /<img[^>]+src=["']([^"']+)["'][^>]*>/gi;
    const matches = Array.from(initialHtml.matchAll(imgRegex));
    const relativeImages = matches
      .map(m => m[1])
      .filter(src => src && !src.startsWith('http') && !src.startsWith('data:') && !src.startsWith('/'));

    if (relativeImages.length === 0) {
      setResolvedHtml(initialHtml);
      return;
    }

    // Resolve each relative image path
    const resolvePromises = relativeImages.map(async (relativeSrc) => {
      // Build absolute path: basePath + relativeSrc
      const normalizedBase = basePath.replace(/\\/g, '/').replace(/\/+$/, '');
      const normalizedSrc = relativeSrc.replace(/\\/g, '/');
      const absolutePath = normalizedSrc.startsWith('./')
        ? `${normalizedBase}/${normalizedSrc.slice(2)}`
        : normalizedSrc.startsWith('../')
          ? resolveParentPath(normalizedBase, normalizedSrc)
          : `${normalizedBase}/${normalizedSrc}`;

      try {
        const result = await readRawFile(absolutePath);
        return { original: relativeSrc, resolved: result.dataUrl };
      } catch {
        // Keep original src if fetch fails
        return { original: relativeSrc, resolved: relativeSrc };
      }
    });

    Promise.all(resolvePromises).then(resolutions => {
      let html = initialHtml;
      for (const { original, resolved } of resolutions) {
        // Replace the src attribute in HTML
        html = html.replace(
          new RegExp(`<img[^>]+src=["'](${escapeRegex(original)})["']`, 'gi'),
          (match) => match.replace(original, resolved)
        );
      }
      setResolvedHtml(html);
    });
  }, [content, basePath, initialHtml]);

  if (!content) return null;

  return <div className="markdown-body" dangerouslySetInnerHTML={{ __html: resolvedHtml || initialHtml }} />;
}

/**
 * Resolve ../ parent directory references.
 */
function resolveParentPath(base: string, relative: string): string {
  const parts = base.split('/');
  const matchResult = relative.match(/^(\.\.\/)+/);
  const upCount = matchResult?.[0]?.split('/').filter(Boolean).length ?? 0;
  const remaining = relative.replace(/^(\.\.\/)+/, '');
  const newBase = parts.slice(0, Math.max(0, parts.length - upCount)).join('/');
  return `${newBase}/${remaining}`;
}

function escapeRegex(str: string): string {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}