"""Wiki knowledge-base module — Markdown + YAML frontmatter KB core implementation."""

from app.wiki.repo import WikiRepository
from app.wiki.cache import WikiCache
from app.wiki.extract import extract_text
from app.wiki.search import tokenized_search
from app.wiki.lint import lint_knowledge_base, LintResult
from app.wiki.graph import build_graph
from app.wiki.tool import KnowledgeBaseTool
from app.wiki.ingest import ingest_file, sync_knowledge_base, parse_file_blocks

__all__ = [
    'WikiRepository',
    'WikiCache',
    'extract_text',
    'tokenized_search',
    'lint_knowledge_base',
    'LintResult',
    'KnowledgeBaseTool',
    'ingest_file',
    'sync_knowledge_base',
    'parse_file_blocks',
    'build_graph',
]
