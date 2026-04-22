import { useMemo } from 'react';
import { marked } from 'marked';

marked.setOptions({ breaks: true, gfm: true });

interface MarkdownContentProps {
  content: string;
}

export function MarkdownContent({ content }: MarkdownContentProps) {
  const html = useMemo(() => {
    if (!content) return '';
    return marked.parse(content, { async: false }) as string;
  }, [content]);

  if (!content) return null;

  return <div className="markdown-body" dangerouslySetInnerHTML={{ __html: html }} />;
}
