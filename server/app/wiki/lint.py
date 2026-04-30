"""Lint health checks — broken links, orphan pages, and missing source detection."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.wiki.repo import WikiRepository, _parse_frontmatter

logger = logging.getLogger('nowork')


@dataclass
class LintResult:
    broken_links: list[dict] = field(default_factory=list)    # {source, target}
    orphan_pages: list[str] = field(default_factory=list)      # orphan page paths
    empty_pages: list[str] = field(default_factory=list)       # empty content page paths
    missing_sources: list[dict] = field(default_factory=list)  # {page, source_path}
    total_pages: int = 0
    total_links: int = 0

    def to_dict(self) -> dict:
        return {
            'broken_links': self.broken_links,
            'orphan_pages': self.orphan_pages,
            'empty_pages': self.empty_pages,
            'missing_sources': self.missing_sources,
            'total_pages': self.total_pages,
            'total_links': self.total_links,
            'healthy': (
                not self.broken_links
                and not self.missing_sources
            ),
            'warnings': len(self.orphan_pages) + len(self.empty_pages),
        }

    @property
    def healthy(self) -> bool:
        return not self.broken_links and not self.missing_sources


WIKILINK_RE = re.compile(r'\[\[([^\]]+)\]\]')


def lint_knowledge_base(kb_id: str) -> LintResult:
    """Structural lint (no LLM required).

    Single-pass implementation: traverses all .md files once to collect
    page IDs, outgoing links, page metadata, and detect issues.

    Checks:
    - Broken links: [[xxx]] target page does not exist
    - Orphan pages: pages with no incoming links
    - Empty pages: only frontmatter, no body content
    - Missing sources: frontmatter.sources references a non-existent file
    """
    repo = WikiRepository(kb_id)
    result = LintResult()

    wiki_dir = repo.wiki_dir
    if not wiki_dir.exists():
        return result

    # -- Single-pass data collection --
    page_ids: set[str] = set()                  # all page IDs (filename stems)
    outgoing_links: dict[str, list[str]] = {}   # {page_path: [target, ...]}
    incoming_ids: set[str] = set()              # all IDs referenced by [[links]]
    page_data_map: dict[str, dict] = {}         # {page_path: {body, meta, page_id}}

    for md_file in wiki_dir.rglob('*.md'):
        rel = f"wiki/{md_file.relative_to(wiki_dir).as_posix()}"
        page_id = md_file.stem

        content = md_file.read_text(encoding='utf-8', errors='replace')
        meta, body = _parse_frontmatter(content)

        page_ids.add(page_id)

        # Collect outgoing wikilinks
        targets = WIKILINK_RE.findall(content)
        if targets:
            outgoing_links[rel] = targets
            for t in targets:
                incoming_ids.add(t)

        page_data_map[rel] = {
            'page_id': page_id,
            'body': body,
            'meta': meta,
        }

    result.total_pages = len(page_data_map)
    result.total_links = sum(len(targets) for targets in outgoing_links.values())

    # -- Check each page --
    special_pages = {'index', 'overview', 'log'}

    for page_path, pdata in page_data_map.items():
        page_id = pdata['page_id']
        body = pdata['body']
        meta = pdata['meta']

        # Empty pages
        if not body.strip():
            result.empty_pages.append(page_path)

        # Missing sources
        sources = meta.get('sources', [])
        for src in sources:
            if src and not Path(src).exists():
                result.missing_sources.append({
                    'page': page_path,
                    'source_path': src,
                })

        # Broken links
        targets = outgoing_links.get(page_path, [])
        for target in targets:
            if target not in page_ids:
                result.broken_links.append({
                    'source': page_path,
                    'target': target,
                })

        # Orphan pages
        if page_id not in special_pages and page_id not in incoming_ids:
            result.orphan_pages.append(page_path)

    return result
