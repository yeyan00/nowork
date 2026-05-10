"""Approval mechanism for tool operations requiring user confirmation.

Architecture:
- ApprovalProvider: Protocol that tools implement to decide if a paused
  tool call can be auto-approved.  services.py calls the provider; it
  never needs to know the tool's internal logic.
- ApprovalManager: Per-session registry of directories the user has
  explicitly approved.  Providers query it as part of their decision.
- services._handle_run_paused: Orchestration only — finds the relevant
  provider, asks it, and either auto-approves or sends a
  ToolApprovalRequest SSE event to the frontend.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Set, runtime_checkable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ApprovalProvider — tools implement this to participate in the approval flow
# ---------------------------------------------------------------------------

@runtime_checkable
class ApprovalProvider(Protocol):
    """Protocol for tools that can auto-approve their own paused operations.

    When agno pauses a run because a tool has `requires_confirmation=True`,
    services.py calls *every* registered ApprovalProvider to check whether
    the specific paused tool call can be auto-approved.

    If no provider claims the tool, the request is forwarded to the user.
    """

    def can_auto_approve(self, tool_name: str, tool_args: dict, session_id: str) -> bool:
        """Return True if this tool call can proceed without user confirmation.

        Args:
            tool_name: Name of the paused tool (e.g. "write_file").
            tool_args: The tool arguments dict (e.g. {"file_path": "/tmp/x.py", ...}).
            session_id: Current session ID (for ApprovalManager lookups).
        """
        ...

    def get_approval_description(self, tool_name: str, tool_args: dict) -> str:
        """Return a human-readable description for the approval dialog.

        Example: "Write to /etc/passwd"
        """
        ...


# ---------------------------------------------------------------------------
# ApprovalManager — per-session directory approval registry
# ---------------------------------------------------------------------------

class ApprovalManager:
    """Manages per-session sets of directories that the user has approved
    for write access (outside of base_dirs).

    Thread-safety: all methods are synchronous and idempotent.  The data
    structure is simple enough that no locking is needed for single-threaded
    async usage (FastAPI runs handlers on the event loop).
    """

    def __init__(self) -> None:
        # session_id → set of approved directory paths (resolved, absolute)
        self._approved: Dict[str, Set[str]] = {}

    # -- mutate -------------------------------------------------------------

    def approve_dir(self, session_id: str, dir_path: str) -> None:
        """Record that the user approved writes to *dir_path* for this session."""
        resolved = str(Path(dir_path).resolve())
        if session_id not in self._approved:
            self._approved[session_id] = set()
        self._approved[session_id].add(resolved)
        logger.info("ApprovalManager: approved dir %s for session %s", resolved, session_id)

    def approve_dirs(self, session_id: str, dir_paths: List[str]) -> None:
        """Record multiple approved directories at once."""
        for d in dir_paths:
            self.approve_dir(session_id, d)

    def clear_session(self, session_id: str) -> None:
        """Remove all approved dirs for a session (cleanup on session end)."""
        self._approved.pop(session_id, None)

    # -- query --------------------------------------------------------------

    def is_dir_approved(self, session_id: str, dir_path: str) -> bool:
        """Check if *dir_path* (or a parent) has been approved for this session."""
        approved = self._approved.get(session_id, set())
        if not approved:
            return False
        try:
            resolved = Path(dir_path).resolve()
        except (OSError, ValueError):
            return False
        for ad in approved:
            try:
                resolved.relative_to(Path(ad).resolve())
                return True
            except (ValueError, OSError):
                pass
        return False

    def get_approved_dirs(self, session_id: str) -> Set[str]:
        """Return a copy of the approved directory set for this session."""
        return set(self._approved.get(session_id, set()))


# Singleton instance shared across the app
approval_manager = ApprovalManager()


# ---------------------------------------------------------------------------
# Helper: find an ApprovalProvider on a runtime agent
# ---------------------------------------------------------------------------

def find_approval_provider(runtime: Any, tool_name: str) -> Optional[ApprovalProvider]:
    """Search runtime.tools for an ApprovalProvider that handles *tool_name*.

    A provider "handles" a tool if:
    - It has a ``handles_tools`` method that returns True for *tool_name*, OR
    - It does not have ``handles_tools`` (assumed to handle all tools — backward compat).

    Returns the first matching provider, or None.
    """
    tools = getattr(runtime, 'tools', None) or []
    for _tool in tools:
        if isinstance(_tool, ApprovalProvider):
            # If the provider declares which tools it handles, check it.
            if hasattr(_tool, 'handles_tools'):
                if _tool.handles_tools(tool_name):
                    return _tool
            else:
                # No declaration — assume it handles everything (backward compat)
                return _tool
    return None
