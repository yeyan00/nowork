"""分词搜索 — CJK bigram + 英文 token 搜索，标题加权。"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

from app.wiki.repo import WikiRepository, _parse_frontmatter


def tokenize_query(query: str) -> list[str]:
    """将查询拆分为 tokens: 英文单词 + CJK bigram。
    
    "transformer 训练方法" → ["transformer", "训练", "练方", "方法"]
    """
    tokens: list[str] = []
    # 英文单词
    en_words = re.findall(r'[a-zA-Z0-9]+', query.lower())
    tokens.extend(w for w in en_words if len(w) >= 2)

    # CJK bigram
    cjk_chars = []
    for ch in query:
        if _is_cjk(ch):
            cjk_chars.append(ch)

    for i in range(len(cjk_chars)):
        if i < len(cjk_chars) - 1:
            tokens.append(cjk_chars[i] + cjk_chars[i + 1])
        # 也添加单字
        tokens.append(cjk_chars[i])

    # 去重但保持顺序
    seen = set()
    unique = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return unique


def _is_cjk(ch: str) -> bool:
    cp = ord(ch)
    return (
        (0x4E00 <= cp <= 0x9FFF)   # CJK Unified
        or (0x3400 <= cp <= 0x4DBF)  # CJK Extension A
        or (0x2E80 <= cp <= 0x2EFF)  # CJK Radicals
        or (0xF900 <= cp <= 0xFAFF)  # CJK Compatibility
        or (0x3000 <= cp <= 0x303F)  # CJK Symbols
        or (0xAC00 <= cp <= 0xD7AF)  # Hangul
        or (0x3040 <= cp <= 0x309F)  # Hiragana
        or (0x30A0 <= cp <= 0x30FF)  # Katakana
    )


def tokenized_search(kb_id: str, query: str, max_results: int = 20) -> list[dict[str, Any]]:
    """分词搜索 Wiki 页面。
    
    标题命中 × 3 加分，内容命中 × 1，related/tag 命中 × 0.5。
    """
    repo = WikiRepository(kb_id)
    wiki_dir = repo.wiki_dir
    if not wiki_dir.exists():
        return []

    tokens = tokenize_query(query)
    if not tokens:
        return []

    results: list[dict[str, Any]] = []

    for md_file in wiki_dir.rglob('*.md'):
        rel = f"wiki/{md_file.relative_to(wiki_dir).as_posix()}"
        content = md_file.read_text(encoding='utf-8', errors='replace')
        meta, body = _parse_frontmatter(content)

        title = str(meta.get('title', md_file.stem))
        title_lower = title.lower()
        body_lower = body.lower()

        related_str = ' '.join(str(r) for r in meta.get('related', []))
        tags_str = ' '.join(str(t) for t in meta.get('tags', []))
        extra_lower = (related_str + ' ' + tags_str).lower()

        score = 0.0
        title_match = False

        for token in tokens:
            token_lower = token.lower()
            if token_lower in title_lower:
                score += 3.0
                title_match = True
            if token_lower in body_lower:
                # 内容命中的次数加分（最多 3 次）
                count = min(body_lower.count(token_lower), 3)
                score += count * 1.0
            if token_lower in extra_lower:
                score += 0.5

        if score > 0:
            results.append({
                'path': rel,
                'title': title,
                'type': str(meta.get('type', '')),
                'score': score,
                'title_match': title_match,
                'summary': body[:300].strip() if body else '',
            })

    # 按分数降序
    results.sort(key=lambda r: r['score'], reverse=True)
    return results[:max_results]
