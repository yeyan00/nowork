"""Localized prompt templates for Wiki Ingest pipeline.

Supports multiple languages. The language is read from the knowledge base
config (``language`` field, default ``"zh"``).

Each prompt function accepts dynamic parameters and returns the complete
prompt string in the requested language.
"""

from __future__ import annotations

_LOCALE_MAP: dict[str, str] = {
    'zh': 'zh',
    'zh-cn': 'zh',
    'zh-tw': 'zh',
    'en': 'en',
    'ja': 'en',
    'ko': 'en',
}


def _resolve(locale: str | None) -> str:
    """Normalize locale string to a supported code.

    Default is English ('en') when locale is not specified.
    """
    if not locale:
        return 'en'
    return _LOCALE_MAP.get(locale.lower().strip(), 'en')


# ── Analysis Prompt (Step 1) ────────────────────────────────────

_ANALYSIS_ZH: list[str] = [
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

_ANALYSIS_EN: list[str] = [
    'You are a professional research analyst. Read the source document and produce a structured analysis.',
    '',
    '## Analysis Requirements',
    '',
    '### Key Entities',
    'List people, organizations, products, datasets, and tools mentioned in the document. For each, provide:',
    '- Name and type',
    '- Role in the source document (central vs. peripheral)',
    '- Whether it likely already exists in the Wiki (check the index below)',
    '',
    '### Key Concepts',
    'List theories, methods, techniques, and phenomena. For each, provide:',
    '- Name and brief definition',
    '- Why it matters in this source document',
    '- Whether it likely already exists in the Wiki',
    '',
    '### Main Arguments and Findings',
    '- What are the core claims or conclusions?',
    '- What evidence supports them?',
    '',
    '### Recommendations',
    '- Which Wiki pages should be created or updated?',
    '- What should be emphasized or de-emphasized?',
    '',
    'Be thorough but concise. Focus on what truly matters.',
]

_ANALYSIS_CTX_ZH = {
    'purpose': '## Wiki 目标（提供上下文）',
    'index': '## 当前 Wiki 索引（用于检查已有内容）',
}

_ANALYSIS_CTX_EN = {
    'purpose': '## Wiki Purpose (context)',
    'index': '## Current Wiki Index (check for existing content)',
}


def analysis_prompt(locale: str | None, purpose: str, index: str) -> str:
    """Build the Step-1 analysis prompt in the given locale."""
    lang = _resolve(locale)
    parts = list(_ANALYSIS_ZH if lang == 'zh' else _ANALYSIS_EN)
    ctx = _ANALYSIS_CTX_ZH if lang == 'zh' else _ANALYSIS_CTX_EN

    if purpose:
        parts.extend(['', ctx['purpose'], purpose])
    if index:
        parts.extend(['', ctx['index'], index])

    return '\n'.join(parts)


# ── Generation Prompt (Step 2) ──────────────────────────────────

def generation_prompt(locale: str | None, schema: str, purpose: str,
                      index: str, source_file_name: str,
                      overview: str) -> str:
    """Build the Step-2 generation prompt in the given locale."""
    lang = _resolve(locale)
    source_base = source_file_name.rsplit('.', 1)[0] if '.' in source_file_name else source_file_name

    if lang == 'zh':
        return _generation_zh(schema, purpose, index, source_file_name, source_base, overview)
    return _generation_en(schema, purpose, index, source_file_name, source_base, overview)


def _generation_zh(schema, purpose, index, source_file_name, source_base, overview) -> str:
    parts = [
        '你是一个 Wiki 维护者。基于提供的分析生成 Wiki 文件。',
        '',
        f'## 重要：源文件\n原始源文件是：**{source_file_name}**',
        '从此源生成的所有 Wiki 页面必须在 frontmatter 的 `sources` 字段中包含此文件名。',
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


def _generation_en(schema, purpose, index, source_file_name, source_base, overview) -> str:
    parts = [
        'You are a Wiki maintainer. Generate Wiki files based on the provided analysis.',
        '',
        f'## Important: Source File\nThe original source file is: **{source_file_name}**',
        'All Wiki pages generated from this source must include this filename in the frontmatter `sources` field.',
        '',
        '## Content to Generate',
        '',
        f'1. A source summary page **wiki/sources/{source_base}.md** (must use this exact path)',
        '2. Key entity pages under wiki/entities/ identified in the analysis',
        '3. Key concept pages under wiki/concepts/ identified in the analysis',
        '4. Update wiki/index.md — add new entries to existing categories, preserve all existing entries',
        '5. A new entry for wiki/log.md (new entries only)',
        '6. Update wiki/overview.md — a comprehensive summary reflecting the newly ingested source (2-5 paragraphs)',
        '',
        '## Frontmatter Rules (critical)',
        '',
        'Every page must have YAML frontmatter:',
        '```yaml',
        '---',
        'type: source | entity | concept | comparison | query | synthesis',
        'title: Human-readable title',
        'created: YYYY-MM-DD',
        'updated: YYYY-MM-DD',
        'tags: []',
        'related: []',
        f'sources: ["{source_file_name}"]',
        '---',
        '```',
        '',
        'Use [[wikilink]] syntax for cross-references between pages. Use kebab-case for filenames.',
        '',
        '## Output Format (must follow strictly)',
        '',
        'Your entire response consists of FILE blocks. Nothing else.',
        '',
        'FILE block template:',
        '```',
        '---FILE: wiki/path/to/page.md---',
        '(full file content including YAML frontmatter)',
        '---END FILE---',
        '```',
        '',
        '## Output Requirements (strict)',
        '',
        '1. The first character of your response must be `-` (start of ---FILE:)',
        '2. Do not output any preamble',
        '3. Do not echo back the analysis',
        '4. Use English for all FILE block content',
    ]

    if purpose:
        parts.extend(['', '## Wiki Purpose', purpose])
    if schema:
        parts.extend(['', '## Structural Rules', schema])
    if index:
        parts.extend(['', '## Current Wiki Index (preserve all existing entries, add new ones)', index])
    if overview:
        parts.extend(['', '## Current Wiki Overview (update to reflect new source)', overview])

    return '\n'.join(parts)


# ── Ingest runtime messages ─────────────────────────────────────

def ingest_run_message(locale: str | None, file_name: str) -> str:
    """Message sent to the analyst agent with the source document."""
    lang = _resolve(locale)
    if lang == 'zh':
        return f'分析这个源文档：\n\n**文件:** {file_name}\n\n---\n\n'
    return f'Analyze this source document:\n\n**File:** {file_name}\n\n---\n\n'


def ingest_generate_message(locale: str | None, file_name: str,
                            analysis_content: str, text: str) -> str:
    """Message sent to the generator agent."""
    lang = _resolve(locale)
    if lang == 'zh':
        return (
            f'源文档处理: **{file_name}**\n\n'
            '以下第一阶段分析仅作上下文，不要重复。\n\n'
            f'## 第一阶段分析\n\n{analysis_content}\n\n'
            f'## 原始源文档内容\n\n{text}\n\n---\n\n'
            f'现在基于 **{file_name}** 生成 Wiki FILE 块。必须以 ---FILE: 开头。'
        )
    return (
        f'Source document processing: **{file_name}**\n\n'
        'The first-stage analysis below is for context only — do not repeat it.\n\n'
        f'## Stage-1 Analysis\n\n{analysis_content}\n\n'
        f'## Original Source Document\n\n{text}\n\n---\n\n'
        f'Now generate Wiki FILE blocks for **{file_name}**. Must start with ---FILE:.'
    )


def fallback_source_summary(locale: str | None, file_name: str,
                            source_path: str) -> str:
    """Fallback source summary page when LLM fails to generate one."""
    from datetime import date
    today = date.today().isoformat()
    lang = _resolve(locale)
    note = (
        '（自动生成的来源摘要页面，原始分析未能生成详细内容。）'
        if lang == 'zh'
        else '(Auto-generated source summary page; the original analysis failed to produce detailed content.)'
    )
    return (
        f'---\ntype: source\n'
        f'title: "Source: {file_name}"\n'
        f'created: {today}\n'
        f'updated: {today}\n'
        f'sources: ["{source_path}"]\n'
        f'tags: []\nrelated: []\n---\n\n'
        f'# Source: {file_name}\n\n'
        f'{note}\n'
    )
