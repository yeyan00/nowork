"""Knowledge graph builder — extract nodes and edges from Wiki [[wikilink]] syntax.

Single-pass implementation: traverses all .md files once to build nodes
and collect edges simultaneously.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.wiki.repo import WikiRepository, _parse_frontmatter

logger = logging.getLogger('nowork')

TYPE_COLORS: dict[str, str] = {
    'entity': '#4c78ff',
    'concept': '#22c55e',
    'source': '#f59e0b',
    'query': '#a855f7',
    'comparison': '#ec4899',
    'synthesis': '#06b6d4',
}

DEFAULT_COLOR = '#8492aa'

WIKILINK_RE = re.compile(r'\[\[([^\]]+)\]\]')


def build_graph(kb_id: str) -> dict[str, Any]:
    """Build the knowledge graph's nodes and edges in a single file traversal.

    Returns:
        {
            "nodes": [{"id", "title", "type", "path", "group"}],
            "edges": [{"source", "target", "source_path"}],
            "stats": {"total_nodes", "total_edges", "by_type", "orphan_nodes"}
        }
    """
    repo = WikiRepository(kb_id)
    wiki_dir = repo.wiki_dir
    if not wiki_dir.exists():
        return {'nodes': [], 'edges': [], 'stats': {'total_nodes': 0, 'total_edges': 0, 'by_type': {}, 'orphan_nodes': []}}

    page_id_to_path: dict[str, str] = {}
    node_map: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, str]] = []
    has_incoming: set[str] = set()

    # -- Single pass: build nodes and edges simultaneously --
    for md_file in wiki_dir.rglob('*.md'):
        rel = f"wiki/{md_file.relative_to(wiki_dir).as_posix()}"
        content = md_file.read_text(encoding='utf-8', errors='replace')
        meta, _body = _parse_frontmatter(content)

        page_id = md_file.stem
        page_type = str(meta.get('type', 'other'))
        title = str(meta.get('title', page_id))

        page_id_to_path[page_id] = rel
        node_map[page_id] = {
            'id': page_id,
            'title': title,
            'type': page_type,
            'path': rel,
            'group': TYPE_COLORS.get(page_type, DEFAULT_COLOR),
        }

        # Collect edges from this page's wikilinks
        targets = WIKILINK_RE.findall(content)
        for target in targets:
            if target in page_id_to_path or target in node_map:
                edges.append({
                    'source': page_id,
                    'target': target,
                    'source_path': rel,
                })
                has_incoming.add(target)
            else:
                # Missing target — create placeholder node
                if target not in node_map:
                    node_map[target] = {
                        'id': target,
                        'title': target,
                        'type': 'missing',
                        'path': '',
                        'group': '#e53935',
                    }
                    page_id_to_path[target] = ''
                edges.append({
                    'source': page_id,
                    'target': target,
                    'source_path': rel,
                })
                has_incoming.add(target)

    nodes = list(node_map.values())

    by_type: dict[str, int] = defaultdict(int)
    for n in nodes:
        by_type[n['type']] += 1

    special_pages = {'index', 'overview', 'log'}
    orphan_nodes = [
        n['id'] for n in nodes
        if n['id'] not in has_incoming and n['id'] not in special_pages and n['type'] != 'missing'
    ]

    return {
        'nodes': nodes,
        'edges': edges,
        'stats': {
            'total_nodes': len(nodes),
            'total_edges': len(edges),
            'by_type': dict(by_type),
            'orphan_nodes': orphan_nodes,
        },
    }
