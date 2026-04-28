"""两步 Ingest 管线 — wiki-analyst + wiki-generator Agno Agent。"""

from __future__ import annotations

import re
import logging
import asyncio
from datetime import date
from pathlib import Path
from typing import Any

from app.wiki.repo import WikiRepository, _parse_frontmatter
from app.wiki.extract import extract_text
from app.wiki.cache import WikiCache

logger = logging.getLogger('nowork')


# ── Prompt 构建 ──────────────────────────────────────────────


def build_analysis_prompt(purpose: str, index: str) -> str:
    """构建分析 Prompt (Step 1)。"""
    parts = [
        '你是一个专业的研究分析师。阅读源文档并生成结构化分析。',
        '',
        '## 分析要求',
        '',
        '### 关键实体',
        '列出文档中提到的人物、组织、产品、数据集、工具。对每个列出：',
        '- 名称和类型',
        '- 在源文档中的角色（核心 vs 边缘）',
        '- 是否可能已经存在于 Wiki 中（检查下方索引）',
        '',
        '### 关键概念',
        '列出理论、方法、技术、现象。对每个列出：',
        '- 名称和简要定义',
        '- 为什么在此源文档中重要',
        '- 是否可能已经存在于 Wiki 中',
        '',
        '### 主要论点和发现',
        '- 核心主张或结论是什么？',
        '- 有什么证据支持？',
        '',
        '### 建议',
        '- 应该创建或更新哪些 Wiki 页面？',
        '- 应该强调什么，弱化什么？',
        '',
        '要详尽但简洁。专注于真正重要的内容。',
    ]

    if purpose:
        parts.extend(['', '## Wiki 目标（提供上下文）', purpose])

    if index:
        parts.extend(['', '## 当前 Wiki 索引（用于检查已有内容）', index])

    return '\n'.join(parts)


def build_generation_prompt(schema: str, purpose: str, index: str,
                            source_file_name: str, overview: str) -> str:
    """构建生成 Prompt (Step 2)。"""
    source_base = Path(source_file_name).stem

    parts = [
        '你是一个 Wiki 维护者。基于提供的分析生成 Wiki 文件。',
        '',
        f'## 重要：源文件\n原始源文件是：**{source_file_name}**',
        f'从此源生成的所有 Wiki 页面必须在 frontmatter 的 `sources` 字段中包含此文件名。',
        '',
        '## 生成内容',
        '',
        f'1. 一个来源摘要页面 **wiki/sources/{source_base}.md**（必须使用此精确路径）',
        '2. 在 wiki/entities/ 下生成分析中识别的关键实体页面',
        '3. 在 wiki/concepts/ 下生成分析中识别的关键概念页面',
        '4. 更新 wiki/index.md — 在现有分类中添加新条目，保留所有已有条目',
        '5. wiki/log.md 的新条目（仅新条目）',
        '6. 更新 wiki/overview.md — 反映新摄入源的全面概要（2-5段）',
        '',
        '## Frontmatter 规则（关键）',
        '',
        '每个页面必须有 YAML frontmatter：',
        '```yaml',
        '---',
        'type: source | entity | concept | comparison | query | synthesis',
        'title: 可读标题',
        'created: YYYY-MM-DD',
        'updated: YYYY-MM-DD',
        'tags: []',
        'related: []',
        f'sources: ["{source_file_name}"]',
        '---',
        '```',
        '',
        '使用 [[wikilink]] 语法进行页面间交叉引用。文件名使用 kebab-case。',
        '',
        '## 输出格式（必须严格遵循）',
        '',
        '你的整个回复由 FILE 块组成。不要有其他内容。',
        '',
        'FILE 块模板：',
        '```',
        '---FILE: wiki/path/to/page.md---',
        '（完整文件内容，含 YAML frontmatter）',
        '---END FILE---',
        '```',
        '',
        '## 输出要求（严格）',
        '',
        '1. 回复的第一个字符必须是 `-`（---FILE: 的开头）',
        '2. 不要输出任何前言',
        '3. 不要回显分析内容',
        '4. 每个 FILE 块的内容使用中文',
    ]

    if purpose:
        parts.extend(['', '## Wiki 目标', purpose])

    if schema:
        parts.extend(['', '## 结构规则', schema])

    if index:
        parts.extend(['', '## 当前 Wiki 索引（保留所有已有条目，添加新的）', index])

    if overview:
        parts.extend(['', '## 当前 Wiki 概要（更新以反映新源）', overview])

    return '\n'.join(parts)


# ── FILE Block 解析 ──────────────────────────────────────────

FILE_OPENER = re.compile(r'^---\s*FILE:\s*(.+?)\s*---\s*$', re.IGNORECASE)
FILE_CLOSER = re.compile(r'^---\s*END\s+FILE\s*---\s*$', re.IGNORECASE)
REVIEW_OPENER = re.compile(r'^---\s*REVIEW:\s*(.+?)\s*---\s*$', re.IGNORECASE)
REVIEW_CLOSER = re.compile(r'^---\s*END\s+REVIEW\s*---\s*$', re.IGNORECASE)


def parse_file_blocks(llm_output: str) -> list[tuple[str, str]]:
    """解析 LLM 输出的 ---FILE: path---...---END FILE--- 块。
    
    Returns: [(path, content), ...]
    """
    blocks: list[tuple[str, str]] = []
    warnings: list[str] = []

    lines = llm_output.split('\n')
    i = 0

    while i < len(lines):
        match = FILE_OPENER.match(lines[i].strip())
        if match:
            path = match.group(1).strip()
            content_lines: list[str] = []
            i += 1

            while i < len(lines):
                if FILE_CLOSER.match(lines[i].strip()):
                    i += 1
                    break
                content_lines.append(lines[i])
                i += 1

            content = '\n'.join(content_lines)

            # 安全检查
            if not path.startswith('wiki/'):
                warnings.append(f'Rejected path outside wiki/: {path}')
            elif '..' in path.split('/') or '..' in path.split('\\'):
                warnings.append(f'Rejected path with ..: {path}')
            else:
                blocks.append((path, content))
        else:
            i += 1

    if warnings:
        logger.warning('FILE block parse warnings: %s', warnings)

    return blocks


# ── Ingest 流程 ──────────────────────────────────────────────

async def ingest_file(kb_id: str, source_path: str, model: Any,
                      force: bool = False) -> list[str]:
    """Ingest 单个文件到 Wiki。
    
    Args:
        kb_id: 知识库 ID
        source_path: 源文件绝对路径
        model: Agno Model 实例
        force: 强制重新 Ingest（忽略缓存）
    
    Returns:
        写入的 Wiki 页面路径列表
    """
    from agno.agent import Agent

    repo = WikiRepository(kb_id)
    cache = WikiCache(repo.cache_dir)

    # 1. 缓存检查
    if not force:
        cached = cache.check_cache(source_path)
        if cached is not None:
            logger.info('Cache hit for %s, skipping', source_path)
            return cached.get('files', [])

    # 2. 提取文本
    text = extract_text(source_path)
    if not text:
        logger.warning('No text extracted from %s', source_path)
        return []

    # 截断过长内容
    if len(text) > 50000:
        text = text[:50000] + '\n\n[...truncated...]'

    # 3. 读取上下文
    purpose = repo.read_purpose()
    index = repo.read_index()
    schema = repo.read_schema()
    overview = repo.read_overview()
    file_name = Path(source_path).name

    # 4. Step 1: 分析
    analyst = Agent(
        name='wiki-analyst',
        model=model,
        instructions=build_analysis_prompt(purpose, index),
    )
    analysis = await analyst.arun(
        f'分析这个源文档：\n\n**文件:** {file_name}\n\n---\n\n{text}'
    )

    # 5. Step 2: 生成
    generator = Agent(
        name='wiki-generator',
        model=model,
        instructions=build_generation_prompt(
            schema, purpose, index, file_name, overview
        ),
    )
    generation = await generator.arun(
        f'源文档处理: **{file_name}**\n\n'
        '以下第一阶段分析仅作上下文，不要重复。\n\n'
        f'## 第一阶段分析\n\n{analysis.content}\n\n'
        f'## 原始源文档内容\n\n{text}\n\n---\n\n'
        f'现在基于 **{file_name}** 生成 Wiki FILE 块。必须以 ---FILE: 开头。'
    )

    # 6. 解析并写入
    blocks = parse_file_blocks(generation.content)
    written: list[str] = []
    for path, content in blocks:
        if repo.write_page(path, content):
            written.append(path)

    # 如果没有生成 source summary，创建一个基础版本
    source_base = Path(source_path).stem
    if not any('sources/' in p for p in written):
        fallback = (
            f'---\ntype: source\n'
            f'title: "Source: {file_name}"\n'
            f'created: {date.today().isoformat()}\n'
            f'updated: {date.today().isoformat()}\n'
            f'sources: ["{source_path}"]\n'
            f'tags: []\nrelated: []\n---\n\n'
            f'# Source: {file_name}\n\n'
            f'（自动生成的来源摘要页面，原始分析未能生成详细内容。）\n'
        )
        repo.write_page(f'wiki/sources/{source_base}.md', fallback)
        written.append(f'wiki/sources/{source_base}.md')

    # 7. 追加日志
    repo.append_log(file_name)

    # 8. 更新缓存
    cache.save_cache(source_path, written)

    # 9. 清除图谱缓存
    repo.bump_version()

    logger.info('Ingested %s → %d wiki pages', file_name, len(written))
    return written


async def sync_knowledge_base(kb_id: str, model: Any, force: bool = False) -> list[str]:
    """同步知识库的所有关联目录。
    
    Args:
        kb_id: 知识库 ID
        model: Agno Model 实例
        force: 强制重新 Ingest
    
    Returns:
        所有写入的 Wiki 页面路径
    """
    from app.config import load_knowledge_config, list_knowledge_refs

    # 找到知识库配置
    kb_cfg = None
    for cfg_raw in _get_all_kb_configs():
        if cfg_raw.get('id') == kb_id:
            kb_cfg = cfg_raw
            break
    if not kb_cfg:
        return []

    paths = kb_cfg.get('paths', [])
    if not paths:
        return []

    repo = WikiRepository(kb_id)
    cache = WikiCache(repo.cache_dir)

    # 扫描变化文件
    changed = cache.scan_changes(paths) if not force else _list_all_files(paths)

    if not changed:
        logger.info('No changes detected for kb %s', kb_id)
        return []

    logger.info('Found %d changed files for kb %s', len(changed), kb_id)

    # 串行 Ingest
    all_written: list[str] = []
    for file_path in changed:
        try:
            written = await ingest_file(kb_id, file_path, model, force=force)
            all_written.extend(written)
        except Exception as e:
            logger.error('Failed to ingest %s: %s', file_path, e)

    return all_written


def _get_all_kb_configs() -> list[dict]:
    from app.config import get_all_knowledge_configs
    return get_all_knowledge_configs()


def _list_all_files(paths: list[str]) -> list[str]:
    """列出所有支持的文件。"""
    from app.wiki.cache import _is_supported_file
    files: list[str] = []
    for p in paths:
        path = Path(p)
        if path.is_file():
            files.append(str(path))
        elif path.is_dir():
            for f in path.rglob('*'):
                if f.is_file() and _is_supported_file(f):
                    files.append(str(f))
    return files
