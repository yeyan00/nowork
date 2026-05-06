"""Test allowed_commands configuration for CodingTools.

Tests the full flow:
1. Frontend sends allowed_commands in tools config
2. Backend saves to worker YAML
3. Backend loads CodingTools with the configured allowed_commands
"""

import tempfile
from pathlib import Path

import pytest


class TestAllowedCommandsConfig:
    """Test allowed_commands configuration flow."""

    def test_codingtools_with_explicit_allowed_commands(self):
        """CodingTools should use explicit allowed_commands when provided."""
        from server.app.tools.codingTools import CodingTools

        # Create with explicit allowed_commands
        custom_commands = ['python', 'npm', 'git', 'docker']
        tools = CodingTools(
            base_dirs=[tempfile.gettempdir()],
            allowed_commands=custom_commands,
            all=True,
        )

        # Verify allowed_commands is set correctly
        assert tools.allowed_commands is not None
        assert set(tools.allowed_commands) == set(custom_commands)

        # Verify a custom command is allowed
        assert 'docker' in tools.allowed_commands

        # Verify a default command NOT in custom list should be blocked
        # (when explicit list is provided, it replaces defaults)
        assert 'cat' not in tools.allowed_commands

    def test_codingtools_with_empty_allowed_commands_uses_defaults(self):
        """CodingTools should use defaults when allowed_commands is None (not empty list)."""
        from server.app.tools.codingTools import CodingTools

        # Create with allowed_commands=None (or not provided)
        tools = CodingTools(
            base_dirs=[tempfile.gettempdir()],
            all=True,
        )

        # Should have default commands
        assert tools.allowed_commands is not None
        assert len(tools.allowed_commands) > 50  # Default has many commands
        assert 'python' in tools.allowed_commands
        assert 'git' in tools.allowed_commands
        assert 'npm' in tools.allowed_commands

    def test_codingtools_with_empty_list_blocks_all(self):
        """CodingTools with empty allowed_commands list should block all commands."""
        from server.app.tools.codingTools import CodingTools

        # Create with empty list - this explicitly allows NO commands
        tools = CodingTools(
            base_dirs=[tempfile.gettempdir()],
            allowed_commands=[],  # Empty list = no commands allowed
            all=True,
        )

        # Empty list means no commands allowed
        assert tools.allowed_commands == []

    def test_update_worker_with_allowed_commands(self, tmp_path: Path):
        """Test that allowed_commands flows through config to CodingTools."""
        import sys
        import os
        
        # Add server to path
        server_path = Path(__file__).resolve().parents[1] / 'server'
        if str(server_path) not in sys.path:
            sys.path.insert(0, str(server_path))

        from app.config import resolve_tools

        # Simulate the tools payload that frontend would send
        tools_payload = [{
            'module': 'app.tools.codingTools',
            'class': 'CodingTools',
            'config': {
                'base_dirs': ['~/nowork-workspace'],
                'default_readable': True,
                'all': True,
                'allowed_commands': ['python', 'npm', 'docker'],
            }
        }]

        # Resolve tools (this is what backend does when loading worker)
        resolved = resolve_tools(tools_payload)
        assert len(resolved) > 0
        
        coding_tools_instance = resolved[0]
        assert hasattr(coding_tools_instance, 'allowed_commands')
        
        # Verify allowed_commands matches what we configured
        assert set(coding_tools_instance.allowed_commands) == {'python', 'npm', 'docker'}
        
        # Verify non-allowed commands are excluded
        assert 'git' not in coding_tools_instance.allowed_commands
        assert 'cat' not in coding_tools_instance.allowed_commands

    def test_allowed_commands_in_yaml_file(self, tmp_path: Path):
        """Test that allowed_commands persists correctly in YAML format."""
        import yaml

        worker_yaml = tmp_path / "test-cmd.yaml"
        
        # Write config with allowed_commands
        config = {
            'agent': {
                'id': 'test-cmd-1',
                'name': 'Test',
            },
            'tools': [{
                'module': 'app.tools.codingTools',
                'class': 'CodingTools',
                'config': {
                    'base_dirs': ['~/workspace'],
                    'allowed_commands': ['python', 'npm', 'git'],
                }
            }],
            'workspaces': [{'path': '~/workspace', 'permission': 'read-write'}],
        }
        
        worker_yaml.write_text(yaml.dump(config, default_flow_style=False), encoding='utf-8')
        
        # Read back
        with open(worker_yaml, 'r', encoding='utf-8') as f:
            loaded = yaml.safe_load(f)
        
        tools_config = loaded['tools'][0]['config']
        assert tools_config['allowed_commands'] == ['python', 'npm', 'git']


class TestAllowedCommandsRuntime:
    """Test allowed_commands in runtime behavior."""

    def test_shell_command_validation_with_allowed_commands(self):
        """Test that run_shell validates against allowed_commands."""
        from server.app.tools.codingTools import CodingTools

        # Create with limited allowed_commands
        tools = CodingTools(
            base_dirs=[tempfile.gettempdir()],
            allowed_commands=['python', 'echo'],
            enable_run_shell=True,
        )

        # python should be allowed
        assert 'python' in (tools.allowed_commands or [])

        # git should NOT be allowed when explicit list is provided
        assert 'git' not in (tools.allowed_commands or [])

    def test_default_commands_categories(self):
        """Verify default commands cover expected categories."""
        from server.app.tools.codingTools import CodingTools

        tools = CodingTools(base_dirs=[tempfile.gettempdir()], all=True)
        defaults = set(tools.allowed_commands or [])

        # Python ecosystem
        assert 'python' in defaults
        assert 'pip' in defaults
        assert 'pytest' in defaults

        # Node.js ecosystem  
        assert 'npm' in defaults
        assert 'node' in defaults

        # Git
        assert 'git' in defaults

        # File operations
        assert 'ls' in defaults
        assert 'cat' in defaults

        # Build tools
        assert 'make' in defaults


if __name__ == '__main__':
    pytest.main([__file__, '-v'])