"""Lint 健康检查 — 断链、孤立页面、缺失来源检测。"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from app.wiki.repo import WikiRepository

logger = logging.getLogger('nowork')


@dataclass
class LintResult:
    broken_links: list[dict] = field(default_factory=list)    # {source, target}
    orphan_pages: list[str] = field(default_factory=list)      # 孤立页面路径
    empty_pages: list[str] = field(default_factory=list)       # 空内容页面路径
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
    """结构性 Lint（不需要 LLM）。
    
    检查:
    - 断链: [[xxx]] 目标页面不存在
    - 孤立页面: 没有任何入链的页面
    - 空页面: 只有 frontmatter 没有内容
    - 缺失来源: frontmatter.sources 中的文件已不存在
    """
    repo = WikiRepository(kb_id)
    result = LintResult()

    wiki_dir = repo.wiki_dir
    if not wiki_dir.exists():
        return result

    # 收集所有页面 ID (用于断链检查)
    all_page_ids = repo.collect_all_page_ids()

    # 收集所有出链 (用于孤立页面检查)
    all_links = repo.collect_all_links()
    result.total_links = sum(len(targets) for targets in all_links.values())

    # 收集所有被引用的页面 ID
    referenced_ids: set[str] = set()
    for targets in all_links.values():
        for target in targets:
            referenced_ids.add(target)

    # 遍历所有页面进行检查
    pages = repo.list_pages()
    result.total_pages = len(pages)

    for page in pages:
        page_path = page['path']
        page_id = Path(page_path).stem

        # 检查空内容
        page_data = repo.read_page(page_path)
        if page_data:
            body = page_data['body'].strip()
            if not body:
                result.empty_pages.append(page_path)

            # 检查缺失来源
            sources = page_data.get('meta', {}).get('sources', [])
            for src in sources:
                if src and not Path(src).exists():
                    result.missing_sources.append({
                        'page': page_path,
                        'source_path': src,
                    })

        # 检查断链
        targets = all_links.get(page_path, [])
        for target in targets:
            if target not in all_page_ids:
                result.broken_links.append({
                    'source': page_path,
                    'target': target,
                })

        # 检查孤立页面 (排除 index/overview/log 等特殊页面)
        special_pages = {'index', 'overview', 'log'}
        if page_id not in special_pages and page_id not in referenced_ids:
            result.orphan_pages.append(page_path)

    return result
