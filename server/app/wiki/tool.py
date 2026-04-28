"""KnowledgeBaseTool — Agno Toolkit for on-demand knowledge base queries.

Tools provided:
- search_knowledge: search Wiki pages first; falls back to raw source files
- read_wiki_page: read a Wiki page
- list_wiki_pages: list pages

Design principle:
  The Worker only sees "the knowledge base returned results" — it does not need
  to know whether the source is a Wiki page or an original file. If the Worker
  has CodingTools and wants to inspect an original file, the instructions will
  reference the paths directory.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from agno.tools import Toolkit

from app.wiki.repo import WikiRepository
from app.wiki.search import tokenized_search
from app.wiki.extract import extract_text

logger = logging.getLogger('nowork')

# Context budget constants
DEFAULT_MAX_CTX = 204_800
PAGE_BUDGET_FRAC = 0.50
PER_PAGE_FRAC = 0.30
PER_PAGE_FLOOR = 5_000

# Raw file fallback limits
SOURCE_FALLBACK_MAX_FILES = 5
SOURCE_FALLBACK_MAX_CHARS = 30_000


class KnowledgeBaseTool(Toolkit):
    """Knowledge base search tool, injected into a Worker Agent."""

    def __init__(self, kb_id: str):
        super().__init__(name=f'knowledge_base_{kb_id}')
        self.kb_id = kb_id
        self.repo = WikiRepository(kb_id)
        self._source_paths: list[str] | None = None
        self.register(self.search_knowledge)
        self.register(self.read_wiki_page)
        self.register(self.list_wiki_pages)

    # ── Internal Helpers ───────────────────────────────────────

    def _get_source_paths(self) -> list[str]:
        """Return raw source directories associated with this KB (from YAML config)."""
        if self._source_paths is not None:
            return self._source_paths

        try:
            from app.knowledge_repo import get_knowledge_base
            kb = get_knowledge_base(self.kb_id)
            if kb:
                raw = kb.get('_raw', kb)
                paths = raw.get('paths', [])
                self._source_paths = [p for p in paths if p and os.path.isdir(p)]
                return self._source_paths
        except Exception as e:
            logger.warning('Failed to load source paths for kb %s: %s', self.kb_id, e)

        self._source_paths = []
        return self._source_paths

    def _find_source_files(self) -> list[str]:
        """List readable files in all raw source directories."""
        _SKIP_EXTS = {
            '.exe', '.dll', '.so', '.dylib', '.bin', '.dat',
            '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico',
            '.zip', '.tar', '.gz', '.rar', '.7z',
            '.woff', '.woff2', '.ttf', '.eot',
            '.mp3', '.mp4', '.avi', '.mov',
            '.pyc', '.pyd', '.class', '.o', '.obj',
        }

        result: list[str] = []
        for dir_path in self._get_source_paths():
            for root, _dirs, files in os.walk(dir_path):
                for fname in files:
                    if fname.startswith('.'):
                        continue
                    ext = os.path.splitext(fname)[1].lower()
                    if ext in _SKIP_EXTS:
                        continue
                    result.append(os.path.join(root, fname))
        return result

    def _try_source_fallback(self, query: str) -> str | None:
        """When Wiki search returns nothing, try to find relevant content in raw source files.

        Uses simple keyword matching: tokenize the query and score files
        by the number of token matches in their content.
        """
        source_files = self._find_source_files()
        if not source_files:
            return None

        # Simple tokenization: split by whitespace and CJK characters
        tokens = _tokenize_simple(query)
        if not tokens:
            return None

        scored: list[tuple[int, str, str]] = []  # (score, filename, text)

        for fpath in source_files:
            try:
                text = extract_text(fpath)
                if text is None:
                    continue
                # Truncate
                if len(text) > SOURCE_FALLBACK_MAX_CHARS:
                    text = text[:SOURCE_FALLBACK_MAX_CHARS]
                # Score by token matches
                lower = text.lower()
                score = sum(1 for tok in tokens if tok.lower() in lower)
                if score > 0:
                    fname = os.path.basename(fpath)
                    scored.append((score, fname, text))
            except Exception:
                continue

        if not scored:
            return None

        # Sort by score, take top N
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:SOURCE_FALLBACK_MAX_FILES]

        parts: list[str] = [
            'No relevant content found in Wiki. '
            'The following is potentially related information extracted from raw source files:\n',
        ]
        for score, fname, text in top:
            snippet = _extract_relevant_snippet(text, tokens, max_chars=5000)
            parts.append(f'### {fname} (relevance: {score})\n\n{snippet}')

        return '\n\n---\n\n'.join(parts)

    # ── Public Tool Methods ────────────────────────────────────

    def search_knowledge(self, query: str, max_results: int = 10) -> str:
        """Search the knowledge base for relevant content.

        First searches curated Wiki pages; if nothing relevant is found,
        automatically falls back to searching raw source files.

        Args:
            query: Search keywords or question.
            max_results: Maximum number of results to return.
        Returns:
            Relevant knowledge content (from Wiki pages or raw source files).
        """
        # Step 1: Search Wiki pages
        results = tokenized_search(self.kb_id, query, max_results=max_results)

        if results:
            page_budget = int(DEFAULT_MAX_CTX * PAGE_BUDGET_FRAC)
            max_page_size = min(page_budget, max(PER_PAGE_FLOOR, int(page_budget * PER_PAGE_FRAC)))

            pages_context: list[str] = []
            used_chars = 0

            for r in results:
                if used_chars >= page_budget:
                    break
                page_data = self.repo.read_page(r['path'])
                if page_data is None:
                    continue

                body = page_data['body']
                if len(body) > max_page_size:
                    body = body[:max_page_size] + '\n\n[...truncated...]'

                entry = f"### {r['title']}\nPath: {r['path']}\n\n{body}"
                if used_chars + len(entry) > page_budget:
                    break

                pages_context.append(entry)
                used_chars += len(entry)

            if pages_context:
                return '\n\n---\n\n'.join(pages_context)

        # Step 2: Wiki returned nothing -> fallback to raw files
        fallback = self._try_source_fallback(query)
        if fallback:
            return fallback

        return 'No relevant knowledge base content found.'

    def read_wiki_page(self, page_path: str) -> str:
        """Read a specific Wiki page from the knowledge base.

        Args:
            page_path: Wiki page path, e.g. 'entities/transformer.md'
        Returns:
            Full page content.
        """
        # Auto-prepend wiki/ prefix
        if not page_path.startswith('wiki/'):
            page_path = f'wiki/{page_path}'

        page_data = self.repo.read_page(page_path)
        if page_data is None:
            return f'Page not found: {page_path}'
        return page_data['content']

    def list_wiki_pages(self, category: str = '') -> str:
        """List Wiki pages in the knowledge base.

        Args:
            category: Optional filter: entities, concepts, sources, queries
        Returns:
            Page list with titles and paths.
        """
        pages = self.repo.list_pages(category=category)
        if not pages:
            return 'No pages in this knowledge base.'

        lines = []
        for p in pages:
            lines.append(f"- [{p.get('type', '?')}] {p.get('title', '?')} ({p.get('path', '?')})")
        return '\n'.join(lines)


# ── Utility Functions ───────────────────────────────────────────

def _tokenize_simple(text: str) -> list[str]:
    """Simple tokenizer: whitespace split + CJK bigram."""
    import re
    tokens: list[str] = []
    # English tokens
    for word in re.findall(r'[a-zA-Z0-9]+', text):
        if len(word) >= 2:
            tokens.append(word)
    # CJK bigrams
    cjk_chars = re.findall(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff]', text)
    for i in range(len(cjk_chars) - 1):
        tokens.append(cjk_chars[i] + cjk_chars[i + 1])
    return tokens


def _extract_relevant_snippet(text: str, tokens: list[str], max_chars: int = 5000) -> str:
    """Extract paragraphs containing the most keyword matches from text."""
    # Split by blank lines
    paragraphs = text.split('\n\n')

    # Score each paragraph
    scored_paras: list[tuple[int, str]] = []
    for para in paragraphs:
        lower = para.lower()
        score = sum(1 for tok in tokens if tok.lower() in lower)
        if score > 0:
            scored_paras.append((score, para))

    if not scored_paras:
        # No paragraph matched -> return file beginning
        return text[:max_chars] + ('...' if len(text) > max_chars else '')

    # Sort by score
    scored_paras.sort(key=lambda x: x[0], reverse=True)

    # Concatenate top paragraphs within max_chars
    result_parts: list[str] = []
    used = 0
    for score, para in scored_paras:
        if used + len(para) > max_chars:
            remaining = max_chars - used
            if remaining > 100:
                result_parts.append(para[:remaining] + '...')
            break
        result_parts.append(para)
        used += len(para) + 2  # +2 for \n\n

    return '\n\n'.join(result_parts)
