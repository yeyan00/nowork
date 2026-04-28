"""Lint health checks — broken links, orphan pages, and missing source detection."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from app.wiki.repo import WikiRepository

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


def lint_knowledge_base(kb_id: str) -> LintResult:
    """Structural lint (no LLM required).

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

    # Collect all page IDs (for broken-link checks)
    all_page_ids = repo.collect_all_page_ids()

    # Collect all outgoing links (for orphan-page checks)
    all_links = repo.collect_all_links()
    result.total_links = sum(len(targets) for targets in all_links.values())

    # Collect all referenced page IDs
    referenced_ids: set[str] = set()
    for targets in all_links.values():
        for target in targets:
            referenced_ids.add(target)

    # Iterate all pages
    pages = repo.list_pages()
    result.total_pages = len(pages)

    for page in pages:
        page_path = page['path']
        page_id = Path(page_path).stem

        # Check empty content
        page_data = repo.read_page(page_path)
        if page_data:
            body = page_data['body'].strip()
            if not body:
                result.empty_pages.append(page_path)

            # Check missing sources
            sources = page_data.get('meta', {}).get('sources', [])
            for src in sources:
                if src and not Path(src).exists():
                    result.missing_sources.append({
                        'page': page_path,
                        'source_path': src,
                    })

        # Check broken links
        targets = all_links.get(page_path, [])
        for target in targets:
            if target not in all_page_ids:
                result.broken_links.append({
                    'source': page_path,
                    'target': target,
                })

        # Check orphan pages (exclude special pages like index/overview/log)
        special_pages = {'index', 'overview', 'log'}
        if page_id not in special_pages and page_id not in referenced_ids:
            result.orphan_pages.append(page_path)

    return result
