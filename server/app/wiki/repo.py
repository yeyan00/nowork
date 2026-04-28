"""Wiki 文件系统操作 — 读写 Wiki 页面、解析 YAML frontmatter、管理目录结构。"""

from __future__ import annotations

import re
import json
import shutil
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from app.config import resolve_server_root

logger = logging.getLogger('nowork')


def _kb_data_dir(kb_id: str) -> Path:
    """获取知识库数据目录: {server_root}/knowledge/{kb_id}/"""
    root = resolve_server_root()
    d = root / 'knowledge' / kb_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """解析 YAML frontmatter，返回 (metadata, body)。
    
    支持格式:
    ---
    key: value
    ---
    body content
    """
    content = content.lstrip('\n')
    if not content.startswith('---'):
        return {}, content

    # 找到第二个 ---
    end = content.find('---', 3)
    if end < 0:
        return {}, content

    fm_text = content[3:end].strip()
    body = content[end + 3:].lstrip('\n')

    try:
        meta = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError:
        meta = {}

    return meta, body


def _serialize_frontmatter(meta: dict[str, Any], body: str) -> str:
    """将 metadata + body 序列化为带 frontmatter 的 Markdown。"""
    fm = yaml.dump(meta, default_flow_style=False, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{fm}\n---\n{body}"


def _safe_wiki_path(path: str) -> bool:
    """安全检查: 路径必须在 wiki/ 下，无 .. 或绝对路径。"""
    if not path.startswith('wiki/'):
        return False
    parts = path.replace('\\', '/').split('/')
    return '..' not in parts


class WikiRepository:
    """Wiki 文件系统仓库。"""

    def __init__(self, kb_id: str):
        self.kb_id = kb_id
        self.data_dir = _kb_data_dir(kb_id)
        self.wiki_dir = self.data_dir / 'wiki'
        self.cache_dir = self.data_dir / '.cache'

    # ── 目录初始化 ──────────────────────────────────────────

    def ensure_structure(self) -> None:
        """确保 Wiki 目录结构存在。"""
        for sub in ('entities', 'concepts', 'sources', 'queries'):
            (self.wiki_dir / sub).mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # 初始化骨架文件（如果不存在）
        if not (self.data_dir / 'purpose.md').exists():
            (self.data_dir / 'purpose.md').write_text('', encoding='utf-8')
        if not (self.data_dir / 'schema.md').exists():
            (self.data_dir / 'schema.md').write_text(
                '## 页面类型\n\n- entity: 实体页面\n- concept: 概念页面\n'
                '- source: 来源摘要\n- query: 问答归档\n',
                encoding='utf-8',
            )
        if not (self.wiki_dir / 'index.md').exists():
            (self.wiki_dir / 'index.md').write_text(
                '# Wiki Index\n\n## Entities\n\n## Concepts\n\n## Sources\n\n',
                encoding='utf-8',
            )
        if not (self.wiki_dir / 'overview.md').exists():
            (self.wiki_dir / 'overview.md').write_text('', encoding='utf-8')
        if not (self.wiki_dir / 'log.md').exists():
            (self.wiki_dir / 'log.md').write_text('# Wiki Log\n\n', encoding='utf-8')

    # ── 骨架文件读写 ────────────────────────────────────────

    def read_purpose(self) -> str:
        p = self.data_dir / 'purpose.md'
        return p.read_text(encoding='utf-8', errors='replace') if p.exists() else ''

    def write_purpose(self, content: str) -> None:
        (self.data_dir / 'purpose.md').write_text(content, encoding='utf-8')

    def read_schema(self) -> str:
        p = self.data_dir / 'schema.md'
        return p.read_text(encoding='utf-8', errors='replace') if p.exists() else ''

    def read_index(self) -> str:
        p = self.wiki_dir / 'index.md'
        return p.read_text(encoding='utf-8', errors='replace') if p.exists() else ''

    def write_index(self, content: str) -> None:
        (self.wiki_dir / 'index.md').write_text(content, encoding='utf-8')

    def read_overview(self) -> str:
        p = self.wiki_dir / 'overview.md'
        return p.read_text(encoding='utf-8', errors='replace') if p.exists() else ''

    def write_overview(self, content: str) -> None:
        (self.wiki_dir / 'overview.md').write_text(content, encoding='utf-8')

    def read_log(self) -> str:
        p = self.wiki_dir / 'log.md'
        return p.read_text(encoding='utf-8', errors='replace') if p.exists() else ''

    def append_log(self, entry: str) -> None:
        p = self.wiki_dir / 'log.md'
        existing = p.read_text(encoding='utf-8', errors='replace') if p.exists() else '# Wiki Log\n\n'
        today = date.today().isoformat()
        p.write_text(f"{existing}\n## [{today}] ingest | {entry}\n\n", encoding='utf-8')

    # ── 页面操作 ────────────────────────────────────────────

    def list_pages(self, category: str = '', search: str = '') -> list[dict[str, Any]]:
        """列出 Wiki 页面。
        
        Args:
            category: 按类型过滤 (entities/concepts/sources/queries)
            search: 按标题/内容关键词过滤
        """
        pages: list[dict[str, Any]] = []

        scan_dirs = []
        if category:
            scan_dirs.append(self.wiki_dir / category)
        else:
            # 也扫描 wiki/ 根目录的文件 (index.md, overview.md, log.md)
            for sub in ('entities', 'concepts', 'sources', 'queries'):
                scan_dirs.append(self.wiki_dir / sub)

        search_lower = search.lower() if search else ''

        for scan_dir in scan_dirs:
            if not scan_dir.exists():
                continue
            for md_file in sorted(scan_dir.rglob('*.md')):
                rel = md_file.relative_to(self.wiki_dir)
                content = md_file.read_text(encoding='utf-8', errors='replace')
                meta, body = _parse_frontmatter(content)

                title = meta.get('title', md_file.stem)
                page_type = meta.get('type', '')

                # 搜索过滤
                if search_lower:
                    if search_lower not in title.lower() and search_lower not in body.lower():
                        continue

                pages.append({
                    'path': f"wiki/{rel.as_posix()}",
                    'title': str(title),
                    'type': str(page_type),
                    'tags': meta.get('tags', []),
                    'related': meta.get('related', []),
                    'sources': meta.get('sources', []),
                    'created': str(meta.get('created', '')),
                    'updated': str(meta.get('updated', '')),
                    'size': len(content),
                    'summary': body[:200].strip() if body else '',
                })

        return pages

    def read_page(self, page_path: str) -> dict[str, Any] | None:
        """读取指定 Wiki 页面。返回 {path, meta, body, content} 或 None。"""
        # 安全检查
        if not _safe_wiki_path(page_path):
            return None

        full = self.data_dir / page_path
        if not full.exists():
            return None

        content = full.read_text(encoding='utf-8', errors='replace')
        meta, body = _parse_frontmatter(content)

        return {
            'path': page_path,
            'meta': meta,
            'body': body,
            'content': content,
        }

    def write_page(self, page_path: str, content: str) -> bool:
        """写入 Wiki 页面。返回是否成功。"""
        if not _safe_wiki_path(page_path):
            logger.warning('Rejected path outside wiki/: %s', page_path)
            return False

        full = self.data_dir / page_path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding='utf-8')
        return True

    def delete_page(self, page_path: str) -> bool:
        """删除 Wiki 页面。"""
        if not _safe_wiki_path(page_path):
            return False

        full = self.data_dir / page_path
        if full.exists():
            full.unlink()
            return True
        return False

    # ── 统计 ────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """获取 Wiki 统计信息。"""
        stats: dict[str, Any] = {
            'total': 0,
            'by_type': {},
            'last_updated': '',
        }

        if not self.wiki_dir.exists():
            return stats

        latest_mtime: float = 0.0
        for md_file in self.wiki_dir.rglob('*.md'):
            content = md_file.read_text(encoding='utf-8', errors='replace')
            meta, _ = _parse_frontmatter(content)
            page_type = str(meta.get('type', 'other'))
            stats['by_type'][page_type] = stats['by_type'].get(page_type, 0) + 1
            stats['total'] += 1

            mtime = md_file.stat().st_mtime
            if mtime > latest_mtime:
                latest_mtime = mtime

        if latest_mtime:
            stats['last_updated'] = datetime.fromtimestamp(latest_mtime).isoformat()

        return stats

    # ── 版本控制 ────────────────────────────────────────────

    def _version_file(self) -> Path:
        return self.data_dir / '.version'

    def get_version(self) -> int:
        vf = self._version_file()
        if vf.exists():
            try:
                return int(vf.read_text().strip())
            except (ValueError, OSError):
                pass
        return 0

    def bump_version(self) -> int:
        v = self.get_version() + 1
        self._version_file().write_text(str(v), encoding='utf-8')
        return v

    # ── 清理 ────────────────────────────────────────────────

    def destroy(self) -> None:
        """删除整个知识库数据目录。"""
        if self.data_dir.exists():
            shutil.rmtree(self.data_dir, ignore_errors=True)

    # ── Wikilink 收集 ───────────────────────────────────────

    WIKILINK_RE = re.compile(r'\[\[([^\]]+)\]\]')

    def collect_all_links(self) -> dict[str, list[str]]:
        """收集所有页面的 [[wikilink]] 出链。
        Returns: {page_path: [target, target, ...]}
        """
        links: dict[str, list[str]] = {}
        if not self.wiki_dir.exists():
            return links

        for md_file in self.wiki_dir.rglob('*.md'):
            rel = f"wiki/{md_file.relative_to(self.wiki_dir).as_posix()}"
            content = md_file.read_text(encoding='utf-8', errors='replace')
            targets = self.WIKILINK_RE.findall(content)
            if targets:
                links[rel] = targets
        return links

    def collect_all_page_ids(self) -> set[str]:
        """收集所有页面的 ID (文件名去掉 .md)。"""
        ids: set[str] = set()
        if not self.wiki_dir.exists():
            return ids
        for md_file in self.wiki_dir.rglob('*.md'):
            ids.add(md_file.stem)
        return ids
