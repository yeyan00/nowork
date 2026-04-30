"""Agent type catalog — defines available agent types and their configuration schemas.

Each agent type has:
- Metadata (id, name, description)
- Prerequisites (link to prerequisites.py)
- Config fields (what the UI should show)
- Supported features (what sections to show/hide)
"""

from __future__ import annotations

from typing import Any

AGENT_TYPES: list[dict[str, Any]] = [
    {
        'id': 'agno',
        'name': 'Agno Agent',
        'description': 'Built-in agent with full tool, skill, knowledge, and learning support.',
        'framework': 'agno',
        'prerequisites': [],
        'supports': ['tools', 'skills', 'mcp', 'knowledge', 'learning', 'history', 'workspaces'],
        'config_fields': [],
    },
    {
        'id': 'pi',
        'name': 'Pi Agent',
        'description': 'Pi coding agent CLI — autonomous coding with built-in tool execution.',
        'framework': 'pi',
        'prerequisites': ['pi'],
        'supports': [],
        'config_fields': [
            {
                'key': 'provider',
                'type': 'select',
                'label': 'Provider',
                'options': ['anthropic', 'openai', 'google', 'openrouter'],
                'default': 'anthropic',
            },
            {
                'key': 'model',
                'type': 'string',
                'label': 'Model',
                'placeholder': 'claude-sonnet-4',
            },
            {
                'key': 'thinking',
                'type': 'select',
                'label': 'Thinking Level',
                'options': ['off', 'minimal', 'low', 'medium', 'high', 'xhigh'],
                'default': 'off',
            },
            {
                'key': 'tools',
                'type': 'string',
                'label': 'Tools',
                'placeholder': 'all (comma-separated, leave empty for all)',
            },
            {
                'key': 'instructions',
                'type': 'textarea',
                'label': 'System Instructions',
                'optional': True,
            },
        ],
    },
    {
        'id': 'claude',
        'name': 'Claude Agent',
        'description': 'Claude Code SDK — Claude as a subprocess with tool execution.',
        'framework': 'claude',
        'prerequisites': ['claude'],
        'supports': ['mcp'],
        'config_fields': [
            {
                'key': 'model',
                'type': 'string',
                'label': 'Model',
                'placeholder': 'claude-sonnet-4-20250514',
            },
            {
                'key': 'allowed_tools',
                'type': 'multiselect',
                'label': 'Allowed Tools',
                'options': ['Read', 'Edit', 'Write', 'Bash', 'WebSearch', 'WebFetch', 'NotebookRead', 'NotebookEdit'],
            },
            {
                'key': 'permission_mode',
                'type': 'select',
                'label': 'Permission Mode',
                'options': ['default', 'acceptEdits', 'plan', 'bypassPermissions'],
                'default': 'acceptEdits',
            },
            {
                'key': 'max_turns',
                'type': 'number',
                'label': 'Max Turns',
                'default': 20,
            },
            {
                'key': 'instructions',
                'type': 'textarea',
                'label': 'System Instructions',
                'optional': True,
            },
        ],
    },
    {
        'id': 'opencode',
        'name': 'OpenCode Agent',
        'description': 'OpenCode CLI — terminal-based coding agent with MCP support.',
        'framework': 'opencode',
        'prerequisites': ['opencode'],
        'supports': [],
        'config_fields': [
            {
                'key': 'model',
                'type': 'string',
                'label': 'Model',
                'placeholder': 'anthropic/claude-sonnet-4',
            },
        ],
    },
]


def get_agent_types() -> list[dict[str, Any]]:
    """Return the full agent type catalog."""
    return AGENT_TYPES


def get_agent_type(type_id: str) -> dict[str, Any] | None:
    """Return a single agent type by ID."""
    for at in AGENT_TYPES:
        if at['id'] == type_id:
            return at
    return None


def get_supported_features(agent_type: str) -> set[str]:
    """Return the set of supported features for an agent type."""
    at = get_agent_type(agent_type)
    if at is None:
        return set()
    return set(at.get('supports', []))
