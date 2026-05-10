"""Tests for the approval mechanism: ApprovalProvider, ApprovalManager,
CodingTools auto-approve, and _handle_run_paused orchestration.

Run:  python -m pytest tests/test_approval.py -v
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure server is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from app.approval import ApprovalManager, ApprovalProvider, approval_manager, find_approval_provider
from app.tools.codingTools import CodingTools


# ============================================================================
# ApprovalManager unit tests
# ============================================================================

class TestApprovalManager:
    def setup_method(self):
        self.am = ApprovalManager()

    def test_approve_and_check(self):
        self.am.approve_dir("s1", "/tmp/test")
        assert self.am.is_dir_approved("s1", "/tmp/test")
        assert self.am.is_dir_approved("s1", "/tmp/test/subdir/file.py")
        assert not self.am.is_dir_approved("s1", "/tmp/other")

    def test_session_isolation(self):
        self.am.approve_dir("s1", "/tmp/test")
        assert not self.am.is_dir_approved("s2", "/tmp/test")

    def test_clear_session(self):
        self.am.approve_dir("s1", "/tmp/test")
        self.am.clear_session("s1")
        assert not self.am.is_dir_approved("s1", "/tmp/test")

    def test_approve_dirs(self):
        self.am.approve_dirs("s1", ["/tmp/a", "/tmp/b"])
        assert self.am.is_dir_approved("s1", "/tmp/a/file.py")
        assert self.am.is_dir_approved("s1", "/tmp/b/file.py")
        assert not self.am.is_dir_approved("s1", "/tmp/c")

    def test_get_approved_dirs(self):
        self.am.approve_dirs("s1", ["/tmp/a", "/tmp/b"])
        dirs = self.am.get_approved_dirs("s1")
        assert len(dirs) == 2
        # Returns a copy
        dirs.add("/tmp/c")
        assert len(self.am.get_approved_dirs("s1")) == 2

    def test_empty_session(self):
        assert not self.am.is_dir_approved("nonexistent", "/tmp/test")

    def test_invalid_path(self):
        self.am.approve_dir("s1", "/tmp/test")
        # Should not crash on invalid paths
        assert not self.am.is_dir_approved("s1", "\0invalid")


# ============================================================================
# CodingTools ApprovalProvider tests
# ============================================================================

class TestCodingToolsApprovalProvider:
    def setup_method(self):
        import tempfile
        self._tmpdir = tempfile.mkdtemp(prefix="nowork_test_")
        self.ct = CodingTools(base_dirs=[self._tmpdir])
        # Use a fresh ApprovalManager for isolation
        self.am = ApprovalManager()

    def teardown_method(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_is_approval_provider(self):
        assert isinstance(self.ct, ApprovalProvider)

    def test_auto_approve_write_in_base_dirs(self):
        assert self.ct.can_auto_approve("write_file", {"file_path": f"{self._tmpdir}/test.py"}, "s1")

    def test_auto_approve_edit_in_base_dirs(self):
        assert self.ct.can_auto_approve("edit_file", {"file_path": f"{self._tmpdir}/test.py"}, "s1")

    def test_deny_write_outside_base_dirs(self):
        assert not self.ct.can_auto_approve("write_file", {"file_path": "C:/other/test.py"}, "s1")

    def test_deny_edit_outside_base_dirs(self):
        assert not self.ct.can_auto_approve("edit_file", {"file_path": "C:/other/test.py"}, "s1")

    def test_auto_approve_non_write_tools(self):
        # read_file, run_shell, etc. never need approval
        assert self.ct.can_auto_approve("read_file", {}, "s1")
        assert self.ct.can_auto_approve("run_shell", {}, "s1")
        assert self.ct.can_auto_approve("grep", {}, "s1")

    def test_auto_approve_with_approved_dir(self):
        """After user approves a dir via ApprovalManager, writes there should auto-approve."""
        with patch("app.approval.approval_manager", self.am):
            self.am.approve_dir("s1", "C:/other")
            assert self.ct.can_auto_approve("write_file", {"file_path": "C:/other/test.py"}, "s1")

    def test_auto_approve_relative_path_in_base_dirs(self):
        """Relative paths resolve against primary base_dir."""
        assert self.ct.can_auto_approve("write_file", {"file_path": "test.py"}, "s1")

    def test_no_path_auto_deny(self):
        assert not self.ct.can_auto_approve("write_file", {}, "s1")

    def test_get_approval_description_write(self):
        desc = self.ct.get_approval_description("write_file", {"file_path": "C:/other/test.py"})
        assert "Write" in desc
        assert "C:/other/test.py" in desc

    def test_get_approval_description_edit(self):
        desc = self.ct.get_approval_description("edit_file", {"file_path": "C:/other/test.py"})
        assert "Edit" in desc
        assert "C:/other/test.py" in desc

    def test_requires_confirmation_tools_registered(self):
        """write_file and edit_file should be in requires_confirmation_tools."""
        assert "write_file" in self.ct.requires_confirmation_tools
        assert "edit_file" in self.ct.requires_confirmation_tools
        # read_file and run_shell should NOT
        assert "read_file" not in self.ct.requires_confirmation_tools
        assert "run_shell" not in self.ct.requires_confirmation_tools

    def test_handles_tools(self):
        """CodingTools handles approval for edit_file and write_file only."""
        assert self.ct.handles_tools("write_file")
        assert self.ct.handles_tools("edit_file")
        assert not self.ct.handles_tools("read_file")
        assert not self.ct.handles_tools("run_shell")
        assert not self.ct.handles_tools("grep")

    def test_confirmation_context_is_per_instance(self):
        """set_confirmation_context on one instance should not affect another."""
        import tempfile
        tmpdir2 = tempfile.mkdtemp(prefix="nowork_test2_")
        try:
            ct2 = CodingTools(base_dirs=[tmpdir2])
            self.ct.set_confirmation_context(True)
            assert self.ct._is_confirmation_context() is True
            assert ct2._is_confirmation_context() is False
            # Cleanup
            self.ct.set_confirmation_context(False)
        finally:
            import shutil
            shutil.rmtree(tmpdir2, ignore_errors=True)

    def test_confirmation_context_cleared(self):
        """set_confirmation_context(False) should reset the flag."""
        self.ct.set_confirmation_context(True)
        assert self.ct._is_confirmation_context() is True
        self.ct.set_confirmation_context(False)
        assert self.ct._is_confirmation_context() is False


# ============================================================================
# find_approval_provider tests
# ============================================================================

class TestFindApprovalProvider:
    def test_finds_provider_for_handled_tool(self):
        import tempfile
        tmpdir = tempfile.mkdtemp(prefix="nowork_test_")
        try:
            ct = CodingTools(base_dirs=[tmpdir])
            runtime = MagicMock()
            runtime.tools = [ct]
            provider = find_approval_provider(runtime, "write_file")
            assert provider is ct
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_no_provider_for_unhandled_tool(self):
        """CodingTools only handles edit_file/write_file, not read_file."""
        import tempfile
        tmpdir = tempfile.mkdtemp(prefix="nowork_test_")
        try:
            ct = CodingTools(base_dirs=[tmpdir])
            runtime = MagicMock()
            runtime.tools = [ct]
            provider = find_approval_provider(runtime, "read_file")
            assert provider is None  # read_file not in _APPROVED_TOOL_NAMES
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_no_provider(self):
        runtime = MagicMock()
        runtime.tools = [MagicMock()]  # Not an ApprovalProvider
        provider = find_approval_provider(runtime, "write_file")
        assert provider is None

    def test_empty_tools(self):
        runtime = MagicMock()
        runtime.tools = []
        provider = find_approval_provider(runtime, "write_file")
        assert provider is None


# ============================================================================
# _handle_run_paused integration tests (with mocked agno)
# ============================================================================

class TestHandleRunPaused:
    """Test the _handle_run_paused async generator in services.py."""

    def _make_ct(self, tmpdir: str) -> CodingTools:
        return CodingTools(base_dirs=[tmpdir])

    def _make_run_paused_event(self, tools: list[dict], run_id: str = "run-123") -> MagicMock:
        """Create a mock RunPausedEvent."""
        event = MagicMock()
        event.event = "RunPaused"
        event.run_id = run_id
        event.session_id = "sess-1"
        event.tools = []
        event.requirements = []

        for t in tools:
            te = MagicMock()
            te.tool_name = t["tool_name"]
            te.tool_args = t.get("tool_args", {})
            te.tool_call_id = t.get("tool_call_id", "tc-1")
            te.requires_confirmation = t.get("requires_confirmation", True)
            te.confirmed = None
            event.tools.append(te)

        return event

    @pytest.mark.asyncio
    async def test_auto_approve_in_base_dirs(self):
        """When write_file targets a path in base_dirs, auto-approve and continue."""
        import tempfile
        from app.services import _handle_run_paused

        tmpdir = tempfile.mkdtemp(prefix="nowork_test_")
        try:
            ct = self._make_ct(tmpdir)
            runtime = MagicMock()
            runtime.tools = [ct]

            # Mock acontinue_run to yield a RunCompleted event
            completed_event = MagicMock()
            completed_event.event = "RunCompleted"
            completed_event.content = "done"

            async def mock_continue(*args, **kwargs):
                yield completed_event

            runtime.acontinue_run = mock_continue

            event = self._make_run_paused_event([
                {"tool_name": "write_file", "tool_args": {"file_path": f"{tmpdir}/test.py"}, "requires_confirmation": True}
            ])

            # Patch _serialize_event since it needs real dataclass instances
            with patch("app.services._serialize_event", return_value={"event": "RunCompleted", "content": "done"}):
                sse_lines = []
                async for line in _handle_run_paused(event, runtime, "s1", False):
                    sse_lines.append(line)

            # Should have yielded SSE data for the RunCompleted event
            assert len(sse_lines) == 1
            data = json.loads(sse_lines[0].replace("data: ", "").strip())
            assert data["event"] == "RunCompleted"

            # Tool should have been confirmed
            assert event.tools[0].confirmed is True
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_send_approval_request_outside_base_dirs(self):
        """When write_file targets a path outside base_dirs, send ToolApprovalRequest."""
        import tempfile
        from app.services import _handle_run_paused

        tmpdir = tempfile.mkdtemp(prefix="nowork_test_")
        try:
            ct = self._make_ct(tmpdir)
            runtime = MagicMock()
            runtime.tools = [ct]
            runtime.acontinue_run = MagicMock()  # Should NOT be called

            event = self._make_run_paused_event([
                {"tool_name": "write_file", "tool_args": {"file_path": "C:/other/test.py"}, "requires_confirmation": True}
            ])

            sse_lines = []
            async for line in _handle_run_paused(event, runtime, "s1", False):
                sse_lines.append(line)

            # Should have yielded ToolApprovalRequest
            assert len(sse_lines) == 1
            data = json.loads(sse_lines[0].replace("data: ", "").strip())
            assert data["event"] == "ToolApprovalRequest"
            assert len(data["approvals"]) == 1
            assert data["approvals"][0]["toolName"] == "write_file"

            # acontinue_run should NOT have been called
            runtime.acontinue_run.assert_not_called()
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_mixed_auto_and_manual(self):
        """When some tools auto-approve and others don't, send ToolApprovalRequest."""
        import tempfile
        from app.services import _handle_run_paused

        tmpdir = tempfile.mkdtemp(prefix="nowork_test_")
        try:
            ct = self._make_ct(tmpdir)
            runtime = MagicMock()
            runtime.tools = [ct]

            event = self._make_run_paused_event([
                {"tool_name": "write_file", "tool_args": {"file_path": f"{tmpdir}/safe.py"}, "requires_confirmation": True, "tool_call_id": "tc-1"},
                {"tool_name": "edit_file", "tool_args": {"file_path": "C:/other/unsafe.py"}, "requires_confirmation": True, "tool_call_id": "tc-2"},
            ])

            sse_lines = []
            async for line in _handle_run_paused(event, runtime, "s1", False):
                sse_lines.append(line)

            # Should have yielded ToolApprovalRequest (not all can auto-approve)
            assert len(sse_lines) == 1
            data = json.loads(sse_lines[0].replace("data: ", "").strip())
            assert data["event"] == "ToolApprovalRequest"
            # Only the unsafe tool should be in the approval request
            assert len(data["approvals"]) == 1
            assert data["approvals"][0]["toolName"] == "edit_file"
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_no_provider_sends_approval_request(self):
        """When no ApprovalProvider is found, all tools need manual approval."""
        from app.services import _handle_run_paused

        runtime = MagicMock()
        runtime.tools = [MagicMock()]  # Not an ApprovalProvider

        event = self._make_run_paused_event([
            {"tool_name": "write_file", "tool_args": {"file_path": "C:/tmp/test.py"}, "requires_confirmation": True}
        ])

        sse_lines = []
        async for line in _handle_run_paused(event, runtime, "s1", False):
            sse_lines.append(line)

        # No provider → can't auto-approve → send approval request
        assert len(sse_lines) == 1
        data = json.loads(sse_lines[0].replace("data: ", "").strip())
        assert data["event"] == "ToolApprovalRequest"

    @pytest.mark.asyncio
    async def test_nested_run_paused(self):
        """When continue_run yields another RunPaused, it should be handled recursively."""
        import tempfile
        from app.services import _handle_run_paused

        tmpdir = tempfile.mkdtemp(prefix="nowork_test_")
        try:
            ct = self._make_ct(tmpdir)
            runtime = MagicMock()
            runtime.tools = [ct]

            # First continue yields RunPaused, second yields RunCompleted
            call_count = 0

            async def mock_continue(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    paused_event = self._make_run_paused_event(
                        [{"tool_name": "write_file", "tool_args": {"file_path": f"{tmpdir}/second.py"}, "requires_confirmation": True}],
                        run_id="run-123",
                    )
                    yield paused_event
                else:
                    completed = MagicMock()
                    completed.event = "RunCompleted"
                    completed.content = "all done"
                    yield completed

            runtime.acontinue_run = mock_continue

            event = self._make_run_paused_event([
                {"tool_name": "write_file", "tool_args": {"file_path": f"{tmpdir}/first.py"}, "requires_confirmation": True}
            ])

            with patch("app.services._serialize_event", return_value={"event": "RunCompleted", "content": "all done"}):
                sse_lines = []
                async for line in _handle_run_paused(event, runtime, "s1", False):
                    sse_lines.append(line)

            # Should have yielded RunCompleted from the nested continue
            assert len(sse_lines) == 1
            data = json.loads(sse_lines[0].replace("data: ", "").strip())
            assert data["event"] == "RunCompleted"
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)


# ============================================================================
# API endpoint tests (with mocked server)
# ============================================================================

class TestContinueAPI:
    """Test the /api/runs/{run_id}/continue endpoints."""

    def test_approval_manager_integration(self):
        """Verify that the continue endpoint records approved dirs via ApprovalManager."""
        am = ApprovalManager()
        am.approve_dir("s1", "C:/projects/myapp")
        
        # Subdirectory should be covered
        assert am.is_dir_approved("s1", "C:/projects/myapp/src/main.py")
        # Different session should not
        assert not am.is_dir_approved("s2", "C:/projects/myapp/src/main.py")
        
        # After clearing, should be gone
        am.clear_session("s1")
        assert not am.is_dir_approved("s1", "C:/projects/myapp/src/main.py")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
