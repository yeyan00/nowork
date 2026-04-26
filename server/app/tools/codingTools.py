"""
Optimized CodingTools for Agno - Inspired by Pi-mono Architecture

Combines pi-mono's best practices with multi-directory support and Windows compatibility.
Features:
- Cross-platform shell execution (Windows CMD, Unix shell detection)
- Multi-directory security model (support for multiple safe directories)
- Pluggable operations interface (for remote execution, SSH, containers)
- Configurable external tools (rg, fd with explicit paths)
- Improved grep/find with fallback to standard tools
- Enhanced streaming and truncation for large outputs
- Windows-aware path handling
"""

import functools
import os
import signal
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile
from contextvars import ContextVar, Token
from pathlib import Path
from textwrap import dedent
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple, Union

from agno.tools import Toolkit
from agno.utils.log import log_error, log_info, logger


# ============================================================================
# Platform Detection and Configuration
# ============================================================================


def get_platform() -> str:
    """Get current platform: 'windows', 'darwin' (macOS), or 'linux'."""
    system = platform.system().lower()
    if system == "windows":
        return "windows"
    elif system == "darwin":
        return "darwin"
    else:
        return "linux"


def _find_git_bash() -> Optional[str]:
    # Priority 1: well-known Git Bash install locations
    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Git" / "bin" / "bash.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Git" / "bin" / "bash.exe",
        Path(os.environ.get("ProgramW6432", r"C:\Program Files")) / "Git" / "bin" / "bash.exe",
    ]
    for c in candidates:
        if c.exists():
            return str(c)

    # Priority 2: shutil.which("bash") — but skip WSL's System32\bash.exe
    shutil_bash = shutil.which("bash")
    if shutil_bash:
        lower = shutil_bash.lower()
        if "system32" not in lower and "windowsapps" not in lower:
            return shutil_bash

    return None


def _detect_shell() -> Tuple[str, List[str]]:
    if get_platform() == "windows":
        git_bash = _find_git_bash()
        if git_bash:
            return (git_bash, ["-c"])
        shell = os.environ.get("COMSPEC", "cmd.exe")
        if shell.lower().endswith("cmd.exe"):
            return ("powershell.exe", ["-NoProfile", "-Command"])
        return (shell, ["/s", "/c"])
    else:
        shell = os.environ.get("SHELL", "/bin/sh")
        return (shell, ["-c"])


def get_shell_env() -> dict:
    """Get environment variables for shell execution."""
    env = os.environ.copy()
    # Ensure critical paths are available
    if "PATH" not in env:
        env["PATH"] = "/usr/local/bin:/usr/bin:/bin"
    
    # Inject current Python runtime directories into PATH
    # so python, pip, pytest etc. are always available in run_shell
    python_dir = os.path.dirname(sys.executable)
    extra_dirs = [python_dir]
    # Windows: pip and other scripts live in Scripts/ subdirectory
    scripts_dir = os.path.join(python_dir, "Scripts")
    if os.path.isdir(scripts_dir):
        extra_dirs.append(scripts_dir)
    
    env["PATH"] = os.pathsep.join(extra_dirs) + os.pathsep + env["PATH"]
    return env


# ============================================================================
# External Tools Configuration
# ============================================================================


class ToolConfig:
    
    _BIN_DIR = Path(__file__).resolve().parent / "bin"
    
    def __init__(
        self,
        rg_path: Optional[str] = None,
        fd_path: Optional[str] = None,
        grep_path: Optional[str] = None,
        find_path: Optional[str] = None,
        shell_path: Optional[str] = None,
    ):
        self.rg_path = rg_path
        self.fd_path = fd_path
        self.grep_path = grep_path
        self.find_path = find_path
        self.shell_path = shell_path
        self._resolved_tools: Dict[str, Optional[str]] = {}
        self._resolved_shell: Optional[Tuple[str, List[str]]] = None
    
    @classmethod
    def _bundled_bin(cls, name: str) -> Optional[str]:
        if get_platform() == "windows":
            candidate = cls._BIN_DIR / f"{name}.exe"
        else:
            candidate = cls._BIN_DIR / name
        if candidate.exists():
            return str(candidate)
        return None
    
    def get_rg_path(self) -> Optional[str]:
        if "rg" not in self._resolved_tools:
            if self.rg_path:
                if Path(self.rg_path).exists():
                    self._resolved_tools["rg"] = self.rg_path
                else:
                    log_error(f"Configured rg_path does not exist: {self.rg_path}")
                    self._resolved_tools["rg"] = None
            else:
                self._resolved_tools["rg"] = self._bundled_bin("rg") or shutil.which("rg")
        return self._resolved_tools["rg"]
    
    def get_fd_path(self) -> Optional[str]:
        if "fd" not in self._resolved_tools:
            if self.fd_path:
                if Path(self.fd_path).exists():
                    self._resolved_tools["fd"] = self.fd_path
                else:
                    log_error(f"Configured fd_path does not exist: {self.fd_path}")
                    self._resolved_tools["fd"] = None
            else:
                self._resolved_tools["fd"] = self._bundled_bin("fd") or shutil.which("fd")
        return self._resolved_tools["fd"]
    
    def get_grep_path(self) -> Optional[str]:
        if "grep" not in self._resolved_tools:
            if self.grep_path:
                if Path(self.grep_path).exists():
                    self._resolved_tools["grep"] = self.grep_path
                else:
                    log_error(f"Configured grep_path does not exist: {self.grep_path}")
                    self._resolved_tools["grep"] = None
            else:
                self._resolved_tools["grep"] = shutil.which("grep")
        return self._resolved_tools["grep"]
    
    def get_find_path(self) -> Optional[str]:
        if "find" not in self._resolved_tools:
            if self.find_path:
                if Path(self.find_path).exists():
                    self._resolved_tools["find"] = self.find_path
                else:
                    log_error(f"Configured find_path does not exist: {self.find_path}")
                    self._resolved_tools["find"] = None
            else:
                self._resolved_tools["find"] = shutil.which("find")
        return self._resolved_tools["find"]
    
    def get_grep_tool(self) -> Optional[str]:
        rg = self.get_rg_path()
        if rg:
            return rg
        return self.get_grep_path()
    
    def get_find_tool(self) -> Optional[str]:
        fd = self.get_fd_path()
        if fd:
            return fd
        return self.get_find_path()
    
    def get_shell_config(self) -> Tuple[str, List[str]]:
        if self._resolved_shell is not None:
            return self._resolved_shell
        if self.shell_path and Path(self.shell_path).exists():
            self._resolved_shell = (self.shell_path, ["-c"])
            return self._resolved_shell
        self._resolved_shell = _detect_shell()
        return self._resolved_shell


# ============================================================================
# Pluggable Operations Interfaces
# ============================================================================


class FileOperations(Protocol):
    """Protocol for pluggable file operations (supports remote execution)."""
    
    def read_file(self, path: str) -> bytes:
        """Read file contents as bytes."""
        ...
    
    def write_file(self, path: str, content: str) -> None:
        """Write content to a file."""
        ...
    
    def access(self, path: str, mode: str = "r") -> None:
        """Check if file is accessible. Raises error if not."""
        ...
    
    def mkdir(self, path: str) -> None:
        """Create a directory."""
        ...


class ShellOperations(Protocol):
    """Protocol for pluggable shell operations (supports remote execution)."""
    
    def exec(
        self,
        command: str,
        cwd: str,
        timeout: Optional[int] = None,
        on_data: Optional[Callable[[str], None]] = None,
    ) -> Tuple[str, int]:
        """
        Execute a shell command.
        
        Returns:
            Tuple of (output, exit_code)
        """
        ...


class LocalFileOperations:
    """Default file operations using local filesystem."""
    
    def read_file(self, path: str) -> bytes:
        return Path(path).read_bytes()
    
    def write_file(self, path: str, content: str) -> None:
        Path(path).write_text(content, encoding="utf-8")
    
    def access(self, path: str, mode: str = "r") -> None:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Path not found: {path}")
        if mode == "r" and not os.access(p, os.R_OK):
            raise PermissionError(f"Cannot read: {path}")
        if mode == "w" and not os.access(p.parent, os.W_OK):
            raise PermissionError(f"Cannot write to: {path}")
    
    def mkdir(self, path: str) -> None:
        Path(path).mkdir(parents=True, exist_ok=True)


def _kill_process_tree(pid: int) -> None:
    """Kill an entire process tree, not just the leader process.

    On Windows the leader (shell) spawns child processes (python, node, …).
    ``TerminateProcess`` only kills the leader, leaving children alive and
    holding pipe handles open, which causes ``communicate()`` to block forever.
    """
    if os.name == 'nt':
        # taskkill /F /T /PID kills the entire tree (all descendants)
        try:
            subprocess.run(
                ['taskkill', '/F', '/T', '/PID', str(pid)],
                capture_output=True,
                timeout=5,
            )
        except Exception:
            # Fallback: at least try to kill the leader
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
    else:
        # POSIX: kill the entire process group
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass


class LocalShellOperations:
    
    def __init__(self, tool_config: Optional[ToolConfig] = None):
        self.tool_config = tool_config
    
    def exec(
        self,
        command: str,
        cwd: str,
        timeout: Optional[int] = None,
        on_data: Optional[Callable[[str], None]] = None,
    ) -> Tuple[str, int]:
        try:
            if self.tool_config:
                shell, shell_args = self.tool_config.get_shell_config()
            else:
                shell, shell_args = _detect_shell()

            proc = subprocess.Popen(
                [shell] + shell_args + [command],
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace',
                env=get_shell_env(),
                # Create a new process group so we can kill the entire tree
                **({'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else
                   {'start_new_session': True}),
            )

            try:
                stdout, stderr = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                # Kill the entire process tree (not just the shell leader)
                _kill_process_tree(proc.pid)
                # Collect any output produced before/during kill
                try:
                    stdout, stderr = proc.communicate(timeout=3)
                except subprocess.TimeoutExpired:
                    stdout, stderr = '', ''
                raise TimeoutError(
                    f"Command timed out after {timeout} seconds.\n"
                    f"Output so far:\n{stdout or ''}{stderr or ''}"
                )

            output = stdout or ''
            if stderr:
                output += stderr

            if on_data:
                on_data(output)

            return output, proc.returncode

        except TimeoutError:
            raise
        except Exception as e:
            raise RuntimeError(f"Failed to execute command: {e}")


# ============================================================================
# Utility Functions
# ============================================================================


@functools.lru_cache(maxsize=None)
def _warn_coding_tools() -> None:
    logger.warning("CodingTools can run arbitrary shell commands, please provide human supervision.")


def _format_size(num_bytes: int) -> str:
    """Format bytes to human-readable size."""
    for unit in ["B", "KB", "MB", "GB"]:
        if num_bytes < 1024:
            return f"{num_bytes:.1f}{unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f}TB"


def _truncate_text(
    text: str,
    max_lines: int,
    max_bytes: int,
) -> Tuple[str, bool, int]:
    """
    Truncate text to configured limits.
    
    Returns:
        Tuple of (truncated_text, was_truncated, total_lines)
    """
    lines = text.split("\n")
    total_lines = len(lines)
    was_truncated = False
    
    # Truncate by lines (keep last N lines)
    if total_lines > max_lines:
        lines = lines[-max_lines:]
        was_truncated = True
    
    result = "\n".join(lines)
    
    # Truncate by bytes
    if len(result.encode("utf-8", errors="replace")) > max_bytes:
        truncated_lines = []
        current_bytes = 0
        
        for line in lines:
            line_bytes = len((line + "\n").encode("utf-8", errors="replace"))
            if current_bytes + line_bytes > max_bytes:
                break
            truncated_lines.append(line)
            current_bytes += line_bytes
        
        result = "\n".join(truncated_lines)
        was_truncated = True
    
    return result, was_truncated, total_lines


# ============================================================================
# Main CodingTools Class
# ============================================================================


class CodingTools(Toolkit):
    """
    Optimized toolkit for coding agents with multi-directory support.
    
    Provides four core tools (read, edit, write, shell) and three optional
    exploration tools (grep, find, ls). Inspired by pi-mono architecture.
    
    Features:
    - Cross-platform shell execution (Windows + Unix)
    - Multi-directory security model
    - Configurable external tools (rg, fd, grep, find)
    - Pluggable operations (for remote execution)
    - Windows/Unix path compatibility
    - Enhanced error handling and streaming
    
    Usage:
        # Basic usage
        tools = CodingTools(base_dirs=["/work", "/data"])
        
        # With explicit tool paths (e.g., Docker, virtual env)
        config = ToolConfig(
            rg_path="/app/bin/ripgrep",
            fd_path="/app/bin/fd",
        )
        tools = CodingTools(
            base_dirs=["/work"],
            tool_config=config,
            enable_grep=True,
            enable_find=True,
        )
    """
    
    # --- Allowed commands per shell type ---
    # Used when the user does not explicitly pass `allowed_commands`.
    # Initialized as empty; populated by _get_default_allowed_commands().

    # Git Bash / Unix shell: full Unix toolchain + external dev tools
    _BASH_COMMANDS: List[str] = [
        # Python
        "python", "python3", "pip", "pip3", "uv", "poetry", "pipx",
        "pytest", "unittest", "black", "ruff", "mypy", "pylint", "flake8",
        # Node.js / Frontend
        "node", "npm", "npx", "yarn", "pnpm", "bun", "deno",
        "tsc", "tsx", "eslint", "prettier", "vite", "vitest", "jest",
        # Rust / Go / Other runtimes
        "cargo", "rustc", "rustup", "go", "ruby", "java", "dotnet",
        # Build tools
        "make", "cmake", "gcc", "g++", "clang", "clang++",
        # VCS
        "git", "gh",
        # Search & text processing
        "grep", "rg", "fd", "find", "sed", "awk", "tr", "cut",
        "sort", "uniq", "diff", "patch", "xargs", "wc",
        # File operations
        "ls", "cat", "head", "tail", "tee",
        "mkdir", "rm", "mv", "cp", "touch", "ln",
        "basename", "dirname", "realpath", "readlink", "file", "stat",
        # Archives
        "tar", "zip", "unzip", "gzip", "gunzip",
        # Network
        "curl", "wget",
        # System info
        "pwd", "which", "whoami", "hostname", "uname", "date",
        "env", "printenv", "echo", "printf",
        "ps", "df", "du", "timeout", "kill",
        # Database clients
        "sqlite3", "psql", "mysql", "redis-cli",
        # Docker
        "docker",
    ]

    # PowerShell: external tools + common cmdlets/aliases
    _POWERSHELL_COMMANDS: List[str] = [
        # External dev tools (shared with Bash)
        "python", "python3", "pip", "pip3", "uv", "poetry",
        "pytest", "node", "npm", "npx", "yarn", "pnpm", "bun",
        "tsc", "eslint", "prettier", "vite", "vitest", "jest",
        "cargo", "rustc", "go", "dotnet", "java",
        "git", "gh", "docker",
        "rg", "fd", "sqlite3",
        "make", "cmake", "gcc", "clang",
        # PowerShell cmdlets
        "Get-ChildItem", "Get-Content", "Get-Item", "Get-Location",
        "Set-Location", "Select-String", "Write-Output", "Write-Host",
        "Test-Path", "Copy-Item", "Move-Item", "Remove-Item",
        "New-Item", "Get-Process", "Get-Service",
        # PowerShell aliases (commonly used by models)
        "ls", "cat", "pwd", "echo", "rm", "cp", "mv", "mkdir",
        "dir", "type", "cls", "clear", "sort", "tee", "curl",
    ]

    # CMD: external tools + CMD builtins
    _CMD_COMMANDS: List[str] = [
        # External dev tools (shared)
        "python", "python3", "pip", "pip3", "uv",
        "pytest", "node", "npm", "npx", "yarn", "pnpm",
        "git", "gh", "docker",
        "cargo", "rustc", "dotnet",
        "rg", "fd", "sqlite3",
        "make", "cmake", "gcc", "clang",
        # CMD builtins
        "dir", "type", "echo", "del", "copy", "move", "mkdir", "rmdir",
        "cls", "set", "findstr", "where", "path",
        "tasklist", "taskkill", "systeminfo", "hostname", "date", "time",
    ]

    DEFAULT_ALLOWED_COMMANDS: List[str] = []  # placeholder; resolved dynamically

    @classmethod
    def _get_default_allowed_commands(cls, tool_config: "ToolConfig") -> List[str]:
        """Select allowed commands based on the detected shell type."""
        shell_cmd, _ = tool_config.get_shell_config()
        shell_base = Path(shell_cmd).stem.lower()
        # IMPORTANT: check PowerShell/CMD BEFORE generic "sh",
        # because "powershell" contains "sh"
        if "powershell" in shell_base or "pwsh" in shell_base:
            return cls._POWERSHELL_COMMANDS
        elif "cmd" in shell_base:
            return cls._CMD_COMMANDS
        elif "bash" in shell_base or "sh" in shell_base or "zsh" in shell_base:
            return cls._BASH_COMMANDS
        else:
            return list(set(cls._BASH_COMMANDS + cls._POWERSHELL_COMMANDS + cls._CMD_COMMANDS))
    
    _TOOL_INSTRUCTIONS = {
        "read_file": dedent("""\
            **read_file** - Read files with line numbers. Use offset and limit to paginate large files.
            - Always read a file before editing it to understand its current contents.
            - Use the line numbers in the output to understand the file structure."""),
        "edit_file": dedent("""\
            **edit_file** - Make precise edits using exact text matching (find and replace).
            - The old_text must match exactly one location in the file, including whitespace and indentation.
            - Include enough surrounding context in old_text to ensure a unique match.
            - Prefer small, focused edits over rewriting entire files."""),
        "write_file": dedent("""\
            **write_file** - Create new files or overwrite existing ones entirely.
            - Use this for creating new files. For modifying existing files, prefer edit_file.
            - Parent directories are created automatically."""),
        "run_shell": dedent("""\
            **run_shell** - Execute shell commands with timeout protection.
            - Use this for: running tests, git operations, installing packages, searching files (grep/find),
              checking system state, compiling code, and any other command-line task.
            - Commands run from the base directory.
            - Output is truncated if too long; the full output is saved to a temp file."""),
        "grep": dedent("""\
            **grep** - Search file contents for a pattern with line numbers.
            - Use for finding code patterns, function definitions, imports, etc.
            - Supports regex patterns and case-insensitive search.
            - Use the include parameter to filter by file type (e.g. "*.py")."""),
        "find": dedent("""\
            **find** - Search for files by glob pattern.
            - Use for discovering files in the project structure.
            - Supports recursive patterns like "**/*.py"."""),
        "ls": dedent("""\
            **ls** - List directory contents.
            - Use for quick directory exploration.
            - Directories are shown with a trailing /."""),
    }
    _current_session_id: ContextVar[Optional[str]] = ContextVar("coding_tools_current_session_id", default=None)

    @classmethod
    def set_current_session(cls, session_id: str) -> Token:
        return cls._current_session_id.set(session_id)

    @classmethod
    def reset_current_session(cls, token: Token) -> None:
        cls._current_session_id.reset(token)

    @classmethod
    def get_current_session(cls) -> Optional[str]:
        return cls._current_session_id.get()
    
    def _build_instructions(self, tool_names: List[str]) -> str:
        """Build instructions string for enabled tools."""
        preamble = (
            f"You have access to coding tools: {', '.join(tool_names)}.\n"
            "With these tools, you can perform any coding task including reading code, making edits,\n"
            "creating files, running tests, using git, installing packages, and searching codebases."
        )

        # Inform the LLM about available workspace directories
        if self.base_dirs:
            dir_lines = []
            for d in self.base_dirs:
                perm = self.workspace_permissions.get(str(d), 'read-write')
                dir_lines.append(f"  - {d} ({perm})")
            dir_list = "\n".join(dir_lines)
            preamble += (
                f"\n\n## Workspace Directories\n"
                f"Your workspace directories (use these as base paths for all file operations):\n"
                f"{dir_list}\n"
                f"Directories marked 'read-only' must not be modified."
            )

        # Build sections, dynamically adjusting run_shell instructions based on operator restrictions
        sections = []
        for name in tool_names:
            if name not in self._TOOL_INSTRUCTIONS:
                continue
            if name == "run_shell":
                # Build allowed commands hint for the model
                allowed_hint = ""
                if self.allowed_commands is not None:
                    allowed_hint = (
                        f"\n- Only the following commands are allowed: "
                        f"{', '.join(sorted(self.allowed_commands))}."
                        f"\n  Do NOT use commands outside this list."
                    )
                if self.allow_shell_operators:
                    sections.append(self._TOOL_INSTRUCTIONS[name] + allowed_hint)
                else:
                    # Operators blocked — instruct model to avoid them, reducing rejected commands
                    sections.append(dedent("""\
                        **run_shell** - Execute shell commands with timeout protection.
                        - Use this for: running tests, git operations, installing packages, searching files (grep/find),
                          checking system state, compiling code, and any other command-line task.
                        - Commands run from the base directory.
                        - Output is truncated if too long; the full output is saved to a temp file.
                        - IMPORTANT: Shell chaining operators (&&, ||, ;, |, >, >>, <, &, $(), `) are NOT allowed.
                          Run each command as a separate run_shell call. Do not pipe, redirect, or chain commands.""") + allowed_hint)
            else:
                sections.append(self._TOOL_INSTRUCTIONS[name])
        
        best_practices = []
        if "read_file" in tool_names and "edit_file" in tool_names:
            best_practices.append("- Read before editing: always read_file before edit_file to see current contents.")
        if "edit_file" in tool_names:
            best_practices.append("- Make small, incremental edits rather than rewriting entire files.")
        if "run_shell" in tool_names:
            best_practices.append("- Run tests after making changes to verify correctness.")
        
        result = preamble + "\n\n## Tool Usage Guidelines\n\n" + "\n\n".join(sections)
        if best_practices:
            result += "\n\n## Best Practices\n" + "\n".join(best_practices)
        
        # Add environment info when run_shell is enabled
        if "run_shell" in tool_names:
            shell_cmd, _shell_args = self.tool_config.get_shell_config()
            platform_name = get_platform()
            python_path = sys.executable
            
            shell_base = Path(shell_cmd).stem.lower()
            if "powershell" in shell_base or "pwsh" in shell_base:
                shell_desc = "PowerShell"
                shell_hint = "Use PowerShell syntax: $env:VAR = 'value', Get-ChildItem, Write-Output, -eq."
            elif "cmd" in shell_base:
                shell_desc = "CMD"
                shell_hint = "Use CMD syntax: set VAR=value, dir, echo. Use & for chaining."
            elif get_platform() == "windows":
                shell_desc = f"Bash ({shell_cmd})"
                shell_hint = "Use Bash syntax: export VAR=value, ls, grep, && for chaining."
            else:
                shell_desc = shell_base.capitalize()
                shell_hint = "Use standard Unix shell syntax: export VAR=value, ls, grep, && for chaining."
            
            env_lines = [
                "## Environment",
                f"- **OS**: {platform_name}",
                f"- **Shell**: {shell_desc} (`{shell_cmd}`)",
                f"- **Python**: `{python_path}` (available in PATH as `python`)",
                f"- **pip**: available in PATH",
                f"- {shell_hint}",
            ]
            result += "\n\n" + "\n".join(env_lines)
        
        return result
    
    def __init__(
        self,
        base_dirs: Optional[Union[str, Path, List[Union[str, Path]]]] = None,
        workspace_permissions: Optional[Dict[str, str]] = None,
        restrict_to_base_dirs: bool = True,
        allow_shell_operators: bool = True,
        max_lines: int = 2000,
        max_bytes: int = 50_000,
        shell_timeout: int = 120,
        enable_read_file: bool = True,
        enable_edit_file: bool = True,
        enable_write_file: bool = True,
        enable_run_shell: bool = True,
        enable_grep: bool = True,
        enable_find: bool = True,
        enable_ls: bool = True,
        instructions: Optional[str] = None,
        add_instructions: bool = True,
        all: bool = False,
        allowed_commands: Optional[List[str]] = None,
        file_operations: Optional[FileOperations] = None,
        shell_operations: Optional[ShellOperations] = None,
        tool_config: Optional[ToolConfig] = None,
        **kwargs: Any,
    ):
        """
        Initialize CodingTools with multi-directory and configurable external tools support.
        
        Args:
            base_dirs: Single directory, list of directories, or None (uses cwd).
                      Can be strings or Path objects.
            restrict_to_base_dirs: If True, file operations restricted to base_dirs.
            allow_shell_operators: If True, allow shell chaining operators (&&, ||, ;, |, >, etc.).
                                   If False, shell operators are blocked and model is instructed not to use them.
                                   Defaults to True.
            max_lines: Maximum lines to return before truncating (default 2000).
            max_bytes: Maximum bytes to return before truncating (default 50KB).
            shell_timeout: Timeout in seconds for shell commands (default 120).
            enable_read_file: Enable the read_file tool.
            enable_edit_file: Enable the edit_file tool.
            enable_write_file: Enable the write_file tool.
            enable_run_shell: Enable the run_shell tool.
            enable_grep: Enable the grep tool (enabled by default, uses rg if available).
            enable_find: Enable the find tool (enabled by default, uses fd if available).
            enable_ls: Enable the ls tool (enabled by default).
            instructions: Custom instructions for the LLM.
            add_instructions: Whether to add instructions to system message.
            all: Enable all tools regardless of individual flags.
            allowed_commands: List of allowed shell command names.
            file_operations: Custom file operations (for remote execution).
            shell_operations: Custom shell operations (for remote execution).
            tool_config: ToolConfig instance for external tools (rg, fd, grep, find).
                        If None, tools will be auto-detected from PATH.
        
        Example:
            # Docker with tools in /app/bin
            config = ToolConfig(
                rg_path="/app/bin/rg",
                fd_path="/app/bin/fd",
            )
            tools = CodingTools(
                base_dirs=["/workspace"],
                tool_config=config,
                enable_grep=True,
                enable_find=True,
            )
        """
        # Parse and normalize base_dirs
        if base_dirs is None:
            self.base_dirs: List[Path] = [Path.cwd().resolve()]
        elif isinstance(base_dirs, (str, Path)):
            self.base_dirs = [Path(base_dirs).expanduser().resolve()]
        elif isinstance(base_dirs, list):
            self.base_dirs = [Path(d).expanduser().resolve() for d in base_dirs]
        else:
            raise ValueError("base_dirs must be a string, Path, or list of strings/Paths")
        
        # Validate all directories exist
        for base_dir in self.base_dirs:
            if not base_dir.exists():
                raise ValueError(f"Directory does not exist: {base_dir}")
            if not base_dir.is_dir():
                raise ValueError(f"Not a directory: {base_dir}")
        
        # Store workspace permission mapping: resolved_path -> 'read-only' | 'read-write'
        self.workspace_permissions: Dict[str, str] = {}
        if workspace_permissions:
            for raw_path, perm in workspace_permissions.items():
                resolved = str(Path(raw_path).expanduser().resolve())
                self.workspace_permissions[resolved] = perm
        
        self.restrict_to_base_dirs = restrict_to_base_dirs
        self.allow_shell_operators = allow_shell_operators
        # Tool configuration (must be resolved before allowed_commands)
        self.tool_config = self._normalize_tool_config(tool_config)
        self.allowed_commands: Optional[List[str]] = (
            allowed_commands if allowed_commands is not None else self._get_default_allowed_commands(self.tool_config)
        )
        self.max_lines = max_lines
        self.max_bytes = max_bytes
        self.shell_timeout = shell_timeout
        self._temp_files: List[str] = []
        self._session_workspaces: Dict[str, Union[Path, List[Path]]] = {}
        
        self.file_ops: FileOperations = file_operations or LocalFileOperations()
        self.shell_ops: ShellOperations = shell_operations or LocalShellOperations(self.tool_config)
        
        # Register cleanup
        import atexit
        atexit.register(self._cleanup_temp_files)
        
        # Log tool availability
        self._log_tool_availability()
        
        # Build enabled tools
        _enabled: List[Tuple[str, Callable]] = []
        if all or enable_read_file:
            _enabled.append(("read_file", self.read_file))
        if all or enable_edit_file:
            _enabled.append(("edit_file", self.edit_file))
        if all or enable_write_file:
            _enabled.append(("write_file", self.write_file))
        if all or enable_run_shell:
            _enabled.append(("run_shell", self.run_shell))
        if all or enable_grep:
            _enabled.append(("grep", self.grep))
        if all or enable_find:
            _enabled.append(("find", self.find))
        if all or enable_ls:
            _enabled.append(("ls", self.ls))
        
        tool_names = [name for name, _ in _enabled]
        tools = [fn for _, fn in _enabled]
        
        if instructions is None:
            resolved_instructions = self._build_instructions(tool_names)
        else:
            resolved_instructions = instructions
        
        super().__init__(
            name="coding_tools",
            tools=tools,
            instructions=resolved_instructions,
            add_instructions=add_instructions,
            **kwargs,
        )
        
        log_info(f"Initialized CodingTools with directories: {[str(d) for d in self.base_dirs]}")
        log_info(f"Platform: {get_platform()}, Shell: {self.tool_config.get_shell_config()[0]}")

    def register_session_workspace(self, session_id: str, workspaces: Union[list[Union[str, Path]], str, Path]) -> None:
        """Register one or more workspaces for a session.
        
        If a list is given, each path is resolved and stored.
        The effective base_dirs for the session become this list (intersected with self.base_dirs).
        """
        paths: list[Path] = []
        raw_list = workspaces if isinstance(workspaces, list) else [workspaces]
        for ws in raw_list:
            resolved = Path(ws).expanduser().resolve()
            if resolved.exists() and resolved.is_dir():
                paths.append(resolved)
        if paths:
            self._session_workspaces[session_id] = paths  # type: ignore[assignment]

    def _get_current_base_dirs(self) -> List[Path]:
        session_id = self.get_current_session()
        if session_id:
            workspaces = self._session_workspaces.get(session_id)
            if workspaces is not None:
                # workspaces is a list of Paths
                if isinstance(workspaces, list):
                    return workspaces if workspaces else self.base_dirs
                # legacy single Path
                return [workspaces]
        return self.base_dirs

    def _get_primary_base_dir(self) -> Path:
        base_dirs = self._get_current_base_dirs()
        if not base_dirs:
            raise ValueError("No base directories configured")
        return base_dirs[0]
    
    @staticmethod
    def _normalize_tool_config(tool_config: Any) -> ToolConfig:
        if tool_config is None:
            return ToolConfig()
        if isinstance(tool_config, ToolConfig):
            return tool_config
        if isinstance(tool_config, dict):
            return ToolConfig(
                shell_path=tool_config.get('shell_path'),
                rg_path=tool_config.get('rg_path'),
                fd_path=tool_config.get('fd_path'),
                grep_path=tool_config.get('grep_path'),
                find_path=tool_config.get('find_path'),
            )
        return ToolConfig()
    
    def _log_tool_availability(self) -> None:
        """Log availability of external tools."""
        tools_info = []
        
        rg = self.tool_config.get_rg_path()
        if rg:
            tools_info.append(f"ripgrep: {rg}")
        
        fd = self.tool_config.get_fd_path()
        if fd:
            tools_info.append(f"fd: {fd}")
        
        grep = self.tool_config.get_grep_path()
        if grep:
            tools_info.append(f"grep: {grep}")
        
        find = self.tool_config.get_find_path()
        if find:
            tools_info.append(f"find: {find}")
        
        if tools_info:
            log_info(f"External tools available: {', '.join(tools_info)}")
        else:
            log_info("Warning: No external search tools (rg/grep/fd/find) found in PATH or configured paths")
    
    def _cleanup_temp_files(self) -> None:
        """Remove temporary files created during execution."""
        for path in self._temp_files:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                pass
        self._temp_files.clear()
    
    def _is_safe_path(self, path: Path) -> bool:
        """Check if path is within allowed base directories."""
        if not self.restrict_to_base_dirs:
            return True
        
        try:
            for base_dir in self._get_current_base_dirs():
                try:
                    path.relative_to(base_dir)
                    return True
                except ValueError:
                    continue
            return False
        except Exception:
            return False
    
    def _resolve_path(self, file_path: str) -> Tuple[bool, Optional[Path]]:
        """
        Resolve a file path safely.
        
        Returns:
            Tuple of (is_safe, resolved_path)
        """
        try:
            path = Path(file_path)
            primary_base_dir = self._get_primary_base_dir()
            
            # If relative, resolve relative to first effective base_dir
            if not path.is_absolute():
                path = primary_base_dir / path
            
            path = path.resolve()
            
            if self._is_safe_path(path):
                return True, path
            else:
                return False, None
        except Exception:
            return False, None
    
    def _check_command(self, command: str) -> Optional[str]:
        """
        Check if shell command is safe to execute.
        
        Returns error message if unsafe, None if safe.
        """
        if not self.restrict_to_base_dirs:
            return None

        effective_base_dirs = self._get_current_base_dirs()
        primary_base_dir = self._get_primary_base_dir()
        
        # Dangerous patterns that enable shell chaining
        if not self.allow_shell_operators:
            dangerous_patterns = ["&&", "||", ";", "|", "$(", "`", ">", ">>", "<", "&"]
            
            for pattern in dangerous_patterns:
                if pattern in command:
                    return f"Error: Shell operator '{pattern}' is not allowed in restricted mode."
        
        try:
            tokens = shlex.split(command)
        except ValueError:
            return "Error: Could not parse shell command."
        
        if not tokens:
            return "Error: Empty command."
        
        # Validate command name
        if self.allowed_commands is not None:
            cmd = tokens[0]
            cmd_base = Path(cmd).name
            if cmd_base not in self.allowed_commands:
                return f"Error: Command '{cmd_base}' not in allowed commands list."
            
            # rm safety: block recursive/force flags and base_dir deletion
            if cmd_base == "rm":
                has_recursive = any(t in tokens for t in ("-r", "-R", "-rf", "-fr", "--recursive", "-rf"))
                if has_recursive:
                    return "Error: Recursive delete (rm -r/-rf) is not allowed. Delete files individually."
                path_tokens = [t for t in tokens[1:] if not t.startswith("-")]
                for pt in path_tokens:
                    try:
                        resolved = (primary_base_dir / pt).resolve() if not Path(pt).is_absolute() else Path(pt).resolve()
                        for bd in effective_base_dirs:
                            if resolved == bd.resolve():
                                return f"Error: Cannot delete base directory: {pt}"
                    except Exception:
                        continue
        
        # Check path tokens don't escape base_dirs
        for i, token in enumerate(tokens):
            if i == 0 or token.startswith("-"):
                continue
            
            if "/" in token or token == ".." or (get_platform() == "windows" and "\\" in token):
                try:
                    path = Path(token)
                    if not path.is_absolute():
                        path = primary_base_dir / path
                    path = path.resolve()
                    
                    if not self._is_safe_path(path):
                        return f"Error: Command references path outside allowed directories: {token}"
                except Exception:
                    continue
        
        return None
    
    def read_file(self, file_path: str, offset: int = 0, limit: Optional[int] = None) -> str:
        """Read a file with line numbers and pagination."""
        try:
            is_safe, resolved_path = self._resolve_path(file_path)
            if not is_safe or resolved_path is None:
                return f"Error: Path '{file_path}' is outside allowed directories"
            
            if not resolved_path.exists():
                return f"Error: File not found: {file_path}"
            
            if not resolved_path.is_file():
                return f"Error: Not a file: {file_path}"
            
            # Detect binary files
            try:
                with open(resolved_path, "rb") as f:
                    chunk = f.read(8192)
                    if b"\x00" in chunk:
                        return f"Error: Binary file detected: {file_path}"
            except Exception:
                pass
            
            contents = resolved_path.read_text(encoding="utf-8", errors="replace")
            
            if not contents:
                return f"File is empty: {file_path}"
            
            lines = contents.split("\n")
            total_lines = len(lines)
            
            # Apply offset and limit
            effective_limit = limit if limit is not None else self.max_lines
            selected_lines = lines[offset : offset + effective_limit]
            
            # Format with line numbers
            max_line_num = offset + len(selected_lines)
            num_width = max(len(str(max_line_num)), 4)
            
            formatted_lines = []
            for i, line in enumerate(selected_lines):
                line_num = offset + i + 1  # 1-based
                formatted_lines.append(f"{line_num:>{num_width}} | {line}")
            
            output = "\n".join(formatted_lines)
            output, was_truncated, _ = _truncate_text(output, self.max_lines, self.max_bytes)
            
            # Add summary footer
            shown_start = offset + 1
            shown_end = offset + len(selected_lines)
            if was_truncated or shown_end < total_lines or offset > 0:
                output += f"\n[Showing lines {shown_start}-{shown_end} of {total_lines} total]"
            
            return output
        
        except UnicodeDecodeError:
            return f"Error: Cannot decode file as text: {file_path}"
        except PermissionError:
            return f"Error: Permission denied: {file_path}"
        except Exception as e:
            log_error(f"Error reading file: {str(e)}")
            return f"Error reading file: {e}"
    
    def edit_file(self, file_path: str, old_text: str, new_text: str) -> str:
        """Edit a file by replacing exact text match."""
        try:
            is_safe, resolved_path = self._resolve_path(file_path)
            if not is_safe or resolved_path is None:
                return f"Error: Path '{file_path}' is outside allowed directories"
            
            if not resolved_path.exists():
                return f"Error: File not found: {file_path}"
            
            if not resolved_path.is_file():
                return f"Error: Not a file: {file_path}"
            
            if not old_text:
                return "Error: old_text cannot be empty"
            
            if old_text == new_text:
                return "No changes needed: old_text and new_text are identical"
            
            contents = resolved_path.read_text(encoding="utf-8")
            
            # Count occurrences
            count = contents.count(old_text)
            
            if count == 0:
                return (
                    f"Error: old_text not found in {file_path}. "
                    "Make sure the text matches exactly (including whitespace and indentation)."
                )
            
            if count > 1:
                return (
                    f"Error: old_text matches {count} locations in {file_path}. "
                    "Provide more surrounding context to make the match unique."
                )
            
            # Perform replacement
            new_contents = contents.replace(old_text, new_text, 1)
            resolved_path.write_text(new_contents, encoding="utf-8")
            
            # Generate unified diff
            import difflib
            old_lines = contents.splitlines(keepends=True)
            new_lines = new_contents.splitlines(keepends=True)
            
            diff = difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile=f"a/{file_path}",
                tofile=f"b/{file_path}",
                n=3,
            )
            diff_output = "".join(diff)
            
            if not diff_output:
                return "Edit applied but no visible diff generated"
            
            diff_output, was_truncated, total_lines = _truncate_text(
                diff_output, self.max_lines, self.max_bytes
            )
            if was_truncated:
                diff_output += f"\n[Diff truncated: {total_lines} lines total]"
            
            log_info(f"Edited {file_path}")
            return diff_output
        
        except PermissionError:
            return f"Error: Permission denied: {file_path}"
        except Exception as e:
            log_error(f"Error editing file: {str(e)}")
            return f"Error editing file: {e}"
    
    def write_file(self, file_path: str, contents: str) -> str:
        """Create or overwrite a file."""
        try:
            is_safe, resolved_path = self._resolve_path(file_path)
            if not is_safe or resolved_path is None:
                return f"Error: Path '{file_path}' is outside allowed directories"
            
            # Create parent directories
            if not resolved_path.parent.exists():
                resolved_path.parent.mkdir(parents=True, exist_ok=True)
            
            resolved_path.write_text(contents, encoding="utf-8")
            
            line_count = len(contents.split("\n"))
            log_info(f"Wrote {file_path}")
            return f"Wrote {line_count} lines to {file_path}"
        
        except PermissionError:
            return f"Error: Permission denied: {file_path}"
        except Exception as e:
            log_error(f"Error writing file: {str(e)}")
            return f"Error writing file: {e}"
    
    def run_shell(self, command: str, timeout: Optional[int] = None) -> str:
        """Execute a shell command and return output."""
        try:
            _warn_coding_tools()
            log_info(f"Running shell command: {command}")
            
            # Check command safety
            path_error = self._check_command(command)
            if path_error:
                return path_error
            
            effective_timeout = timeout if timeout is not None else self.shell_timeout
            
            # Use current session workspace or default base_dir as working directory
            cwd = str(self._get_primary_base_dir())
            
            try:
                output, exit_code = self.shell_ops.exec(
                    command, cwd, timeout=effective_timeout
                )
            except TimeoutError:
                return f"Error: Command timed out after {effective_timeout} seconds"
            except RuntimeError as e:
                return f"Error: {str(e)}"
            
            header = f"Exit code: {exit_code}\n"
            truncated_output, was_truncated, total_lines = _truncate_text(
                output, self.max_lines, self.max_bytes
            )
            
            if was_truncated:
                # Save full output to temp file
                tmp = tempfile.NamedTemporaryFile(
                    mode="w",
                    delete=False,
                    suffix=".txt",
                    prefix="coding_tools_",
                )
                tmp.write(output)
                tmp.close()
                self._temp_files.append(tmp.name)
                truncated_output += f"\n[Output truncated: {total_lines} lines total. Full output saved to: {tmp.name}]"
            
            return header + truncated_output
        
        except Exception as e:
            log_error(f"Error running shell command: {str(e)}")
            return f"Error running shell command: {e}"
    
    def grep(
        self,
        pattern: str,
        path: Optional[str] = None,
        ignore_case: bool = False,
        include: Optional[str] = None,
        context: int = 0,
        limit: int = 100,
    ) -> str:
        """Search file contents for a pattern."""
        try:
            if not pattern:
                return "Error: Pattern cannot be empty"
            
            # Resolve search path
            if path:
                is_safe, resolved_path = self._resolve_path(path)
                if not is_safe or resolved_path is None:
                    return f"Error: Path '{path}' is outside allowed directories"
            else:
                resolved_path = self._get_primary_base_dir()
            
            if not resolved_path.exists():
                return f"Error: Path not found: {path or '.'}"
            
            # Get the best available grep tool
            grep_tool = self.tool_config.get_grep_tool()
            if not grep_tool:
                return "Error: grep/rg command not found. Install grep or ripgrep."
            
            is_rg = "rg" in grep_tool
            
            # Build command based on tool
            cmd = [grep_tool]
            
            if is_rg:
                # ripgrep syntax
                cmd.extend(["--line-number", "--no-heading"])
                if ignore_case:
                    cmd.append("--ignore-case")
                if context > 0:
                    cmd.extend([f"--context={context}"])
                if include:
                    cmd.extend(["--glob", include])
            else:
                # grep syntax
                cmd.extend(["-rn"])
                if ignore_case:
                    cmd.append("-i")
                if context > 0:
                    cmd.extend([f"-C{context}"])
                if include:
                    cmd.extend(["--include", include])
            
            cmd.append(pattern)
            cmd.append(str(resolved_path))
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(self._get_primary_base_dir()),
            )
            
            output = result.stdout
            if not output:
                if result.returncode == 1:
                    return f"No matches found for pattern: {pattern}"
                if result.stderr:
                    return f"Error: {result.stderr.strip()}"
                return f"No matches found for pattern: {pattern}"
            
            # Make paths relative
            base_str = str(resolved_path) + os.sep
            output = output.replace(base_str, "")
            
            # Enforce match limit
            output_lines = output.split("\n")
            if len(output_lines) > limit:
                output = "\n".join(output_lines[:limit])
                output += f"\n[Results limited to {limit} matches]"
            
            output, was_truncated, total_lines = _truncate_text(
                output, self.max_lines, self.max_bytes
            )
            if was_truncated:
                output += f"\n[Output truncated: {total_lines} lines total]"
            
            return output
        
        except subprocess.TimeoutExpired:
            return "Error: grep timed out after 30 seconds"
        except FileNotFoundError as e:
            return f"Error: Command not found: {e}"
        except Exception as e:
            log_error(f"Error running grep: {str(e)}")
            return f"Error running grep: {e}"
    
    def find(self, pattern: str, path: Optional[str] = None, limit: int = 500) -> str:
        """Search for files by glob pattern."""
        try:
            if not pattern:
                return "Error: Pattern cannot be empty"
            
            # Resolve search path
            if path:
                is_safe, resolved_path = self._resolve_path(path)
                if not is_safe or resolved_path is None:
                    return f"Error: Path '{path}' is outside allowed directories"
            else:
                resolved_path = self._get_primary_base_dir()
            
            if not resolved_path.exists():
                return f"Error: Path not found: {path or '.'}"
            
            if not resolved_path.is_dir():
                return f"Error: Not a directory: {path}"
            
            # Try to use fd first, fall back to pathlib glob
            fd_tool = self.tool_config.get_fd_path()
            
            if fd_tool:
                # Use fd if available
                try:
                    result = subprocess.run(
                        [fd_tool, "--max-one-result"] if limit == 1 else [fd_tool],
                        ["-type", "f" if not pattern.endswith("/") else "d"],
                        [pattern],
                        ["-x", "echo"] if limit else [],
                        cwd=str(resolved_path),
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    
                    if result.stdout:
                        output_lines = result.stdout.strip().split("\n")
                        if len(output_lines) > limit:
                            output = "\n".join(output_lines[:limit])
                            output += f"\n[Results limited to {limit} entries]"
                        else:
                            output = result.stdout.strip()
                        return output
                except Exception:
                    pass  # Fall through to pathlib
            
            # Fall back to pathlib glob
            matches = []
            for match in resolved_path.glob(pattern):
                try:
                    rel_path = match.relative_to(resolved_path)
                    suffix = "/" if match.is_dir() else ""
                    matches.append(str(rel_path) + suffix)
                except ValueError:
                    continue
                
                if len(matches) >= limit:
                    break
            
            if not matches:
                return f"No files found matching pattern: {pattern}"
            
            result = "\n".join(sorted(matches))
            
            if len(matches) >= limit:
                result += f"\n[Results limited to {limit} entries]"
            
            return result
        
        except Exception as e:
            log_error(f"Error finding files: {str(e)}")
            return f"Error finding files: {e}"
    
    def ls(self, path: Optional[str] = None, limit: int = 500) -> str:
        """List directory contents."""
        try:
            # Resolve path
            if path:
                is_safe, resolved_path = self._resolve_path(path)
                if not is_safe or resolved_path is None:
                    return f"Error: Path '{path}' is outside allowed directories"
            else:
                resolved_path = self._get_primary_base_dir()
            
            if not resolved_path.exists():
                return f"Error: Path not found: {path or '.'}"
            
            if not resolved_path.is_dir():
                return f"Error: Not a directory: {path}"
            
            entries = []
            for entry in sorted(resolved_path.iterdir(), key=lambda p: p.name.lower()):
                suffix = "/" if entry.is_dir() else ""
                entries.append(entry.name + suffix)
                if len(entries) >= limit:
                    break
            
            if not entries:
                return f"Directory is empty: {path or '.'}"
            
            result = "\n".join(entries)
            
            if len(entries) >= limit:
                result += f"\n[Listing limited to {limit} entries]"
            
            return result
        
        except PermissionError:
            return f"Error: Permission denied: {path or '.'}"
        except Exception as e:
            log_error(f"Error listing directory: {str(e)}")
            return f"Error listing directory: {e}"