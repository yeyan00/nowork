"""KnowledgeBaseTool — Agno Toolkit，供 Worker 按需查询知识库。

工具设计:
- search_knowledge: 先搜 Wiki 页面 → 找不到时自动从原始文件中提取相关内容
- read_wiki_page: 读取 Wiki 页面
- list_wiki_pages: 列出页面

设计原则:
  Worker 看到的就是"知识库搜索返回了结果"，不需要知道来源是 Wiki 页面还是原始文件。
  如果 Worker 有 CodingTools 且想深入看某个原始文件原文，instructions 里会告知 paths 目录。
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

# 上下文预算常量
DEFAULT_MAX_CTX = 204_800
PAGE_BUDGET_FRAC = 0.50
PER_PAGE_FRAC = 0.30
PER_PAGE_FLOOR = 5_000

# 原始文件 fallback 上限
SOURCE_FALLBACK_MAX_FILES = 5
SOURCE_FALLBACK_MAX_CHARS = 30_000


class KnowledgeBaseTool(Toolkit):
    """知识库搜索工具，注入到 Worker Agent 中。"""

    def __init__(self, kb_id: str):
        super().__init__(name=f'knowledge_base_{kb_id}')
        self.kb_id = kb_id
        self.repo = WikiRepository(kb_id)
        self._source_paths: list[str] | None = None
        self.register(self.search_knowledge)
        self.register(self.read_wiki_page)
        self.register(self.list_wiki_pages)

    # ── 内部辅助 ──────────────────────────────────────────────

    def _get_source_paths(self) -> list[str]:
        """获取知识库关联的原始文件目录列表（从 YAML 配置读取）。"""
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
        """列出所有原始目录中可读取的文件。"""
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
        """Wiki 搜不到时，从原始文件中尝试找相关内容。

        做简单的关键词匹配：把 query 的 token 拆出来，
        在文件内容中做粗筛，返回最相关的几个文件片段。
        """
        source_files = self._find_source_files()
        if not source_files:
            return None

        # 简单分词：按空格和 CJK 字符拆分
        tokens = _tokenize_simple(query)
        if not tokens:
            return None

        scored: list[tuple[int, str, str]] = []  # (score, filename, text)

        for fpath in source_files:
            try:
                text = extract_text(fpath)
                if text is None:
                    continue
                # 截断
                if len(text) > SOURCE_FALLBACK_MAX_CHARS:
                    text = text[:SOURCE_FALLBACK_MAX_CHARS]
                # 计算匹配分
                lower = text.lower()
                score = sum(1 for tok in tokens if tok.lower() in lower)
                if score > 0:
                    fname = os.path.basename(fpath)
                    scored.append((score, fname, text))
            except Exception:
                continue

        if not scored:
            return None

        # 按分数排序，取前 N 个
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:SOURCE_FALLBACK_MAX_FILES]

        parts: list[str] = ['⚠️ Wiki 中未找到相关内容，以下是从原始文件中提取的可能相关信息：\n']
        for score, fname, text in top:
            # 只截取匹配 token 附近的段落
            snippet = _extract_relevant_snippet(text, tokens, max_chars=5000)
            parts.append(f'### 📄 {fname} (相关度: {score})\n\n{snippet}')

        return '\n\n---\n\n'.join(parts)

    # ── 公共工具方法 ──────────────────────────────────────────

    def search_knowledge(self, query: str, max_results: int = 10) -> str:
        """搜索知识库中的相关内容。

        先搜索已整理的 Wiki 页面；如果 Wiki 中没有找到相关内容，
        会自动从知识库关联的原始文件中查找相关信息。

        Args:
            query: 搜索关键词或问题
            max_results: 最多返回的结果数量
        Returns:
            相关知识内容（来自 Wiki 页面或原始文件）
        """
        # ── 第一步：搜 Wiki 页面 ──
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

        # ── 第二步：Wiki 没找到 → 自动读原始文件 ──
        fallback = self._try_source_fallback(query)
        if fallback:
            return fallback

        return '未找到相关知识库内容。'

    def read_wiki_page(self, page_path: str) -> str:
        """读取知识库中的特定 Wiki 页面。

        Args:
            page_path: Wiki 页面路径，如 'entities/transformer.md'
        Returns:
            页面完整内容
        """
        # 自动补全 wiki/ 前缀
        if not page_path.startswith('wiki/'):
            page_path = f'wiki/{page_path}'

        page_data = self.repo.read_page(page_path)
        if page_data is None:
            return f'页面不存在: {page_path}'
        return page_data['content']

    def list_wiki_pages(self, category: str = '') -> str:
        """列出知识库中的 Wiki 页面。

        Args:
            category: 可选筛选类别: entities, concepts, sources, queries
        Returns:
            页面列表，包含标题和路径
        """
        pages = self.repo.list_pages(category=category)
        if not pages:
            return '知识库中没有页面。'

        lines = []
        for p in pages:
            lines.append(f"- [{p.get('type', '?')}] {p.get('title', '?')} ({p.get('path', '?')})")
        return '\n'.join(lines)


# ── 纯函数工具 ────────────────────────────────────────────────

def _tokenize_simple(text: str) -> list[str]:
    """简单分词：空格分割 + CJK 双字分割。"""
    import re
    tokens: list[str] = []
    # 英文 token
    for word in re.findall(r'[a-zA-Z0-9]+', text):
        if len(word) >= 2:
            tokens.append(word)
    # CJK bigram
    cjk_chars = re.findall(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff]', text)
    for i in range(len(cjk_chars) - 1):
        tokens.append(cjk_chars[i] + cjk_chars[i + 1])
    return tokens


def _extract_relevant_snippet(text: str, tokens: list[str], max_chars: int = 5000) -> str:
    """从文本中提取包含关键词的段落。

    找到包含最多 token 的段落，返回其周围上下文。
    """
    # 按空行/双换行分段
    paragraphs = text.split('\n\n')

    # 给每个段落打分
    scored_paras: list[tuple[int, str]] = []
    for para in paragraphs:
        lower = para.lower()
        score = sum(1 for tok in tokens if tok.lower() in lower)
        if score > 0:
            scored_paras.append((score, para))

    if not scored_paras:
        # 没有段落匹配 → 返回文件开头
        return text[:max_chars] + ('...' if len(text) > max_chars else '')

    # 按分数排序
    scored_paras.sort(key=lambda x: x[0], reverse=True)

    # 拼接高分段落，控制在 max_chars 以内
    result_parts: list[str] = []
    used = 0
    for score, para in scored_paras:
        if used + len(para) > max_chars:
            # 截取这个段落
            remaining = max_chars - used
            if remaining > 100:
                result_parts.append(para[:remaining] + '...')
            break
        result_parts.append(para)
        used += len(para) + 2  # +2 for \n\n

    return '\n\n'.join(result_parts)
