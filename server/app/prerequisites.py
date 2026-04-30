"""Prerequisites checker and installer for external agent types.

Each external agent (pi, claude, opencode) requires a CLI on PATH.
All CLIs are installed via npm. npm requires Node.js.
On Windows, Node.js can be installed via winget.

API:
  GET  /api/prerequisites/{agent_type}  → check status
  POST /api/prerequisites/install       → SSE install stream
"""

from __future__ import annotations

import asyncio
import logging
import platform
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

logger = logging.getLogger('nowork')

# ── Prerequisite Chain Definitions ─────────────────────────────

@dataclass
class PrerequisiteStep:
    id: str
    name: str
    check_cmd: str | None = None          # shutil.which() target
    version_args: list[str] | None = None  # e.g. ['--version']
    install_cmd: str | None = None         # command to run if missing
    install_label: str | None = None       # user-facing label

    def check(self) -> tuple[bool, str | None]:
        """Check if this prerequisite is met. Returns (installed, version)."""
        if not self.check_cmd:
            return True, None

        path = shutil.which(self.check_cmd)
        if path is None:
            return False, None

        version = None
        if self.version_args:
            try:
                result = subprocess.run(
                    [self.check_cmd, *self.version_args],
                    capture_output=True, text=True, timeout=10,
                )
                # Some CLIs output version to stderr (e.g., npm wrappers on Windows)
                output = (result.stdout or '').strip()
                if not output:
                    output = (result.stderr or '').strip()
                # Take first line only
                version = output.split('\n')[0] if output else None
            except Exception:
                version = '?'

        return True, version


def _get_node_install_cmd() -> str | None:
    """Return the command to install Node.js on the current platform."""
    system = platform.system()
    if system == 'Windows':
        if shutil.which('winget'):
            return 'winget install -e --id OpenJS.NodeJS.LTS --accept-package-agreements --accept-source-agreements'
        return None
    elif system == 'Darwin':
        if shutil.which('brew'):
            return 'brew install node'
        return None
    else:  # Linux
        return 'curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash - && sudo apt-get install -y nodejs'


# Per-agent-type prerequisite chains (checked in order)
AGENT_PREREQUISITES: dict[str, list[PrerequisiteStep]] = {
    'pi': [
        PrerequisiteStep(
            id='node', name='Node.js',
            check_cmd='node', version_args=['--version'],
            install_cmd=_get_node_install_cmd(),
            install_label='Install Node.js (via winget)',
        ),
        PrerequisiteStep(
            id='npm', name='npm',
            check_cmd='npm', version_args=['--version'],
        ),
        PrerequisiteStep(
            id='pi', name='Pi CLI',
            check_cmd='pi', version_args=['--version'],
            install_cmd='npm install -g @mariozechner/pi-coding-agent',
            install_label='Install Pi CLI (npm)',
        ),
    ],
    'claude': [
        PrerequisiteStep(
            id='node', name='Node.js',
            check_cmd='node', version_args=['--version'],
            install_cmd=_get_node_install_cmd(),
            install_label='Install Node.js (via winget)',
        ),
        PrerequisiteStep(
            id='npm', name='npm',
            check_cmd='npm', version_args=['--version'],
        ),
        PrerequisiteStep(
            id='claude', name='Claude Code CLI',
            check_cmd='claude', version_args=['--version'],
            install_cmd='npm install -g @anthropic-ai/claude-code',
            install_label='Install Claude Code (npm)',
        ),
    ],
    'opencode': [
        PrerequisiteStep(
            id='node', name='Node.js',
            check_cmd='node', version_args=['--version'],
            install_cmd=_get_node_install_cmd(),
            install_label='Install Node.js (via winget)',
        ),
        PrerequisiteStep(
            id='npm', name='npm',
            check_cmd='npm', version_args=['--version'],
        ),
        PrerequisiteStep(
            id='opencode', name='OpenCode CLI',
            check_cmd='opencode', version_args=['--version'],
            install_cmd='npm install -g opencode-ai',
            install_label='Install OpenCode (npm)',
        ),
    ],
}




# ── Public API ──────────────────────────────────────────────────

def check_prerequisites(agent_type: str) -> dict[str, Any]:
    """Check all prerequisites for the given agent type.

    Returns a dict with:
      - ready: bool — all prerequisites met
      - chain: list of step results
      - missing: list of missing step IDs
      - install_cmd: the next install command to run (first missing step)
    """
    steps = AGENT_PREREQUISITES.get(agent_type, [])
    if not steps:
        return {'ready': True, 'chain': [], 'missing': [], 'install_cmd': None}

    chain: list[dict[str, Any]] = []
    missing: list[str] = []
    next_install_cmd: str | None = None
    next_install_label: str | None = None

    blocked = False
    for step in steps:
        if blocked:
            # Earlier prerequisite missing — can't check this one
            chain.append({
                'id': step.id,
                'name': step.name,
                'installed': False,
                'version': None,
                'blocked': True,
            })
            missing.append(step.id)
            continue

        installed, version = step.check()
        chain.append({
            'id': step.id,
            'name': step.name,
            'installed': installed,
            'version': version,
            'blocked': False,
            'install_cmd': step.install_cmd,
            'install_label': step.install_label,
        })

        if not installed:
            missing.append(step.id)
            blocked = True
            if next_install_cmd is None and step.install_cmd:
                next_install_cmd = step.install_cmd
                next_install_label = step.install_label

    return {
        'ready': len(missing) == 0,
        'chain': chain,
        'missing': missing,
        'install_cmd': next_install_cmd,
        'install_label': next_install_label,
    }


async def stream_install(command: str) -> AsyncIterator[str]:
    """Execute an install command and yield SSE-formatted progress events.

    Each yielded string is a complete SSE data line (including 'data: ' prefix).
    """
    # Determine the shell command
    system = platform.system()
    if system == 'Windows':
        cmd_args = ['cmd', '/c', command]
    else:
        cmd_args = ['sh', '-c', command]

    logger.info('Installing prerequisite: %s', command)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,  # merge stderr into stdout
        )

        buffer = ''
        async for raw_chunk in proc.stdout:
            chunk = raw_chunk.decode(errors='replace')
            buffer += chunk

            # Yield complete lines
            while '\n' in buffer:
                line, buffer = buffer.split('\n', 1)
                import json
                yield f"data: {json.dumps({'event': 'stdout', 'content': line})}\n\n"

        # Yield remaining buffer
        if buffer.strip():
            import json
            yield f"data: {json.dumps({'event': 'stdout', 'content': buffer})}\n\n"

        await proc.wait()

        import json
        if proc.returncode == 0:
            yield f"data: {json.dumps({'event': 'done', 'exit_code': 0})}\n\n"
            logger.info('Install succeeded: %s', command)
        else:
            yield f"data: {json.dumps({'event': 'done', 'exit_code': proc.returncode})}\n\n"
            logger.warning('Install failed (exit %d): %s', proc.returncode, command)

    except Exception as e:
        import json
        logger.exception('Install error: %s', e)
        yield f"data: {json.dumps({'event': 'error', 'content': str(e)})}\n\n"
