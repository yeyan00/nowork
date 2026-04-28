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
        "browser-use"
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
            **read_file** - Read text files with line numbers.
            - Use this before editing to understand the current contents and nearby code style.
            - Use `offset` and `limit` to paginate large files. `offset` is 0-based, so `offset=0` starts at line 1.
            - Output may be truncated by line or byte limits. If you need the rest of a file, call read_file again with a larger offset.
            - The footer shows which line range was returned and the total line count when available."""),
        "edit_file": dedent("""\
            **edit_file** - Make precise edits using exact text matching (find and replace).
            - The `old_text` must match exactly one location in the file, including whitespace and indentation.
            - Include enough surrounding context in `old_text` to ensure a unique match.
            - Prefer small, focused edits over rewriting entire files.
            - If an edit fails because the text is missing or ambiguous, read more surrounding context and try again with a more specific match."""),
        "write_file": dedent("""\
            **write_file** - Create new files or overwrite existing files entirely.
            - Use this for creating new files or replacing an entire file.
            - For targeted changes to an existing file, prefer edit_file.
            - Parent directories are created automatically."""),
        "run_shell": dedent("""\
            **run_shell** - Execute shell commands with timeout protection.
            - Use this for running tests, git operations, installing packages, checking system state, building code, and other command-line tasks.
            - For codebase exploration, prefer grep/find/ls before using shell commands.
            - Commands run from the active workspace or base directory.
            - Output may be truncated by line or byte limits. When truncated, the full output is saved to a temp file and its path is returned.
            - If command output is too large, narrow the command scope or inspect the saved temp file."""),
        "grep": dedent("""\
            **grep** - Search file contents for a pattern with line numbers.
            - Use this to find definitions, imports, call sites, configuration keys, and repeated text patterns.
            - Supports regex patterns, case-insensitive search, optional context lines, and file filtering with `include`.
            - Prefer this over run_shell for most content searches.
            - Matched file paths in the results may be returned relative to the searched directory.
            - Results may be limited or truncated when there are too many matches."""),
        "find": dedent("""\
            **find** - Search for matching paths by glob pattern.
            - Use this to discover files and directories in the project structure before reading or editing them.
            - Supports recursive patterns like "**/*.py".
            - Prefer this over run_shell for most file discovery tasks.
            - Results may be limited when there are too many matches."""),
        "ls": dedent("""\
            **ls** - List directory contents.
            - Use this for quick directory exploration before reading files in detail.
            - Directories are shown with a trailing `/`.
            - Results may be limited when a directory contains many entries."""),
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
                f"Your workspace directories (full read-write access):\n"
                f"{dir_list}"
            )

        # Inform about read access scope
        if self.default_readable:
            preamble += (
                f"\n\n## Read Access\n"
                f"Read tools (read_file, grep, find, ls) can access any non-system, non-sensitive directory.\n"
                f"Write tools (edit_file, write_file) are restricted to workspace directories only.\n"
                f"Only read files when the user explicitly asks or when searching for relevant information."
            )
        elif self.readable_extra:
            extra_lines = "\n".join(f"  - {d}" for d in self.readable_extra)
            preamble += (
                f"\n\n## Additional Read-Only Directories\n"
                f"{extra_lines}"
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
            best_practices.append("- For large files, read in chunks with offset and limit instead of assuming the first read returned the full file.")
        if "edit_file" in tool_names:
            best_practices.append("- Make small, incremental edits rather than rewriting entire files.")
            best_practices.append("- Follow existing conventions in nearby code before introducing new patterns or dependencies.")
        if "grep" in tool_names or "find" in tool_names or "ls" in tool_names:
            best_practices.append("- Explore first: prefer ls/find/grep for codebase discovery before using run_shell for ad-hoc searching.")
        if "run_shell" in tool_names:
            best_practices.append("- Run relevant verification commands after making changes when the project provides them.")
            best_practices.append("- If shell output is truncated, inspect the saved temp file or rerun a narrower command.")
        
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
        default_readable: bool = True,
        readable_extra: Optional[List[str]] = None,
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
        
        Access model (three-tier):
            Tier 1 — base_dirs:       Full access (read + write + shell)
            Tier 2 — default readable: Read-only (non-system, non-sensitive paths)
            Tier 3 — blocked:          System/sensitive directories (no access)
        
        Args:
            base_dirs: Single directory, list of directories, or None (uses cwd).
                      Can be strings or Path objects.
            workspace_permissions: Deprecated. Kept for backward compatibility.
            restrict_to_base_dirs: If True, write operations restricted to base_dirs.
                                   Read operations respect default_readable.
            default_readable: If True (default), read_file/grep/find/ls can access
                              any non-system, non-sensitive directory without explicit
                              configuration. Write operations still require base_dirs.
            readable_extra: Additional read-only directories (used to override blocklist).
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
        self.default_readable = default_readable
        self.readable_extra: List[Path] = []
        if readable_extra:
            self.readable_extra = [Path(d).expanduser().resolve() for d in readable_extra]
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
        """Register one or more session-scoped directories.
        
        Session-specific directories extend the toolkit's configured base_dirs rather
        than replacing them. This preserves access to the worker's primary workspace
        while allowing extra readable directories such as skill folders.
        """
        paths: list[Path] = []
        raw_list = workspaces if isinstance(workspaces, list) else [workspaces]
        for ws in raw_list:
            resolved = Path(ws).expanduser().resolve()
            if resolved.exists() and resolved.is_dir():
                paths.append(resolved)
        if paths:
            merged: list[Path] = []
            for candidate in [*self.base_dirs, *paths]:
                if candidate not in merged:
                    merged.append(candidate)
            self._session_workspaces[session_id] = merged  # type: ignore[assignment]

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
    
    # ── Path security: three-tier access model ─────────────────────
    # Tier 1: base_dirs → full access (read + write)
    # Tier 2: default readable → read-only (non-system, non-sensitive)
    # Tier 3: blocked → system/sensitive directories

    _SYSTEM_BLOCKLIST_WIN: List[str] = [
        r'C:\Windows', r'C:\Program Files', r'C:\Program Files (x86)',
        r'C:\ProgramData',
    ]
    _SYSTEM_BLOCKLIST_UNIX: List[str] = [
        '/usr', '/etc', '/var', '/sys', '/proc', '/dev', '/boot',
        '/root', '/sbin', '/bin', '/lib', '/lib64',
    ]
    _SYSTEM_BLOCKLIST_MACOS: List[str] = [
        '/System', '/Library', '/private/var', '/private/etc',
    ]
    # Sensitive path name components (checked anywhere in path)
    _SENSITIVE_NAMES: set = {
        '.ssh', '.gnupg', '.aws', '.kube', '.credentials',
        '.env', 'credentials', 'id_rsa', 'id_ed25519',
    }

    @classmethod
    def _is_system_path(cls, path: Path) -> bool:
        """Check if a path is in the system/sensitive blocklist."""
        import platform
        resolved = str(path.resolve())
        lower = resolved.lower()

        # Windows system directories
        if platform.system() == 'Windows':
            for bl in cls._SYSTEM_BLOCKLIST_WIN:
                if lower.startswith(bl.lower()):
                    return True

        # Unix system directories (also applies to macOS)
        if platform.system() != 'Windows':
            for bl in cls._SYSTEM_BLOCKLIST_UNIX:
                if resolved.startswith(bl):
                    return True
            if platform.system() == 'Darwin':
                for bl in cls._SYSTEM_BLOCKLIST_MACOS:
                    if resolved.startswith(bl):
                        return True

        # Sensitive name components (check each part of the path)
        parts = path.parts
        for part in parts:
            if part.lower() in cls._SENSITIVE_NAMES:
                return True

        return False

    def _is_in_base_dirs(self, path: Path) -> bool:
        """Check if path is within base_dirs (Tier 1 — full access)."""
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

    def _is_read_allowed(self, path: Path) -> bool:
        """Check if path is readable (Tier 1 or Tier 2)."""
        # Tier 1: in base_dirs → always readable
        if self._is_in_base_dirs(path):
            return True

        # If restrict_to_base_dirs and no default_readable → only base_dirs
        if self.restrict_to_base_dirs and not self.default_readable:
            # Check readable_extra whitelist
            for rd in self.readable_extra:
                try:
                    path.relative_to(rd)
                    return True
                except ValueError:
                    continue
            return False

        if not self.default_readable:
            return False

        # Tier 2: default readable — allow non-system, non-sensitive paths
        if self._is_system_path(path):
            # Still check readable_extra (whitelist override for blocklist)
            for rd in self.readable_extra:
                try:
                    path.relative_to(rd)
                    return True
                except ValueError:
                    continue
            return False

        return True

    def _is_safe_path(self, path: Path) -> bool:
        """Check if path is within allowed directories (backward compat: read access)."""
        if not self.restrict_to_base_dirs:
            return True
        return self._is_read_allowed(path)

    def _is_write_allowed(self, path: Path) -> bool:
        """Check if path is writable (must be in base_dirs — Tier 1 only)."""
        return self._is_in_base_dirs(path)
    
    def _resolve_path(self, file_path: str, *, write: bool = False) -> Tuple[bool, Optional[Path]]:
        """
        Resolve a file path safely.

        Args:
            file_path: Path to resolve
            write: If True, check write permission (base_dirs only)

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

            if write:
                if self._is_write_allowed(path):
                    return True, path
                return False, None
            else:
                if self._is_read_allowed(path):
                    return True, path
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
        """Read a text file with line numbers and pagination.

        Returns the selected slice of the file with 1-based line numbers prefixed
        to each line. Use this before editing files and use pagination for large
        files.

        :param file_path: Path to the file to read, relative to an allowed workspace
            directory or an absolute allowed path.
        :param offset: 0-based line offset to start reading from. ``offset=0`` starts
            from line 1.
        :param limit: Maximum number of file lines to return before formatting. If not
            provided, the default configured line window is used.
        :return: Formatted file contents, or an error message. Output may be truncated
            by the configured line and byte limits. When more content remains, the
            result includes a footer showing the returned line range and total lines.
        """
        try:
            is_safe, resolved_path = self._resolve_path(file_path)
            if not is_safe or resolved_path is None:
                return f"Error: Path '{file_path}' is not readable (system/sensitive directory)"
            
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
        """Edit a file by replacing a single exact text match.

        This tool is intended for precise, surgical edits to existing files.
        The old text must match exactly once, including whitespace and indentation.

        :param file_path: Path to the file to edit, relative to an allowed workspace
            directory or an absolute allowed path.
        :param old_text: Exact text to find in the file. Include enough surrounding
            context to make the match unique.
        :param new_text: Replacement text for the matched block.
        :return: A unified diff showing the applied change, or an error message. Diff
            output may be truncated by the configured line and byte limits.
        """
        try:
            is_safe, resolved_path = self._resolve_path(file_path, write=True)
            if not is_safe or resolved_path is None:
                return f"Error: Path '{file_path}' is not writable (only workspace directories allow writing)"
            
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
        """Create a new file or overwrite an existing file completely.

        Use this for new files or when replacing the entire contents of a file.
        For targeted edits to existing files, prefer ``edit_file``.

        :param file_path: Path to the file to create or overwrite, relative to an
            allowed workspace directory or an absolute allowed path.
        :param contents: Full contents to write to the file.
        :return: A short success message with the number of lines written, or an
            error message.
        """
        try:
            is_safe, resolved_path = self._resolve_path(file_path, write=True)
            if not is_safe or resolved_path is None:
                return f"Error: Path '{file_path}' is not writable (only workspace directories allow writing)"
            
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
        """Execute a shell command in the active workspace and return its output.

        This tool is intended for tests, git operations, builds, package commands,
        environment inspection, and other command-line tasks.

        :param command: Shell command to execute.
        :param timeout: Optional timeout in seconds. If not provided, the toolkit's
            default shell timeout is used.
        :return: Command output prefixed with the exit code, or an error message.
            Output may be truncated by the configured line and byte limits. When
            truncation occurs, the full output is saved to a temporary file and the
            returned text includes that file path.
        """
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
        """Search file contents for a text pattern.

        Uses ripgrep when available and falls back to grep-compatible behavior.
        Prefer this over shell commands for most content searches.

        :param pattern: Regex or plain-text pattern to search for.
        :param path: Optional directory or file path to search within. Defaults to
            the active workspace or primary base directory.
        :param ignore_case: If True, perform a case-insensitive search.
        :param include: Optional file glob filter such as ``*.py``.
        :param context: Number of context lines to include before and after matches.
        :param limit: Maximum number of matched output lines to return before adding a
            results-limited notice.
        :return: Matching lines with file paths and line numbers, or an error message.
            Returned file paths may be relative to the searched directory. Output
            may also be truncated by the configured line and byte limits.
        """
        try:
            if not pattern:
                return "Error: Pattern cannot be empty"
            
            # Resolve search path
            if path:
                is_safe, resolved_path = self._resolve_path(path)
                if not is_safe or resolved_path is None:
                    return f"Error: Path '{path}' is not readable (system/sensitive directory)"
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
        """Search for matching paths by glob pattern.

        Uses fd when available and falls back to pathlib-based glob matching.
        Prefer this over shell commands for most file discovery tasks.

        :param pattern: Glob pattern to match, such as ``*.py`` or ``**/*.json``.
        :param path: Optional directory to search within. Defaults to the active
            workspace or primary base directory.
        :param limit: Maximum number of matching entries to return.
        :return: Matching relative paths, or an error message. Results can include
            files and directories depending on the pattern and backend behavior.
            When too many matches are found, the result includes a results-limited notice.
        """
        try:
            if not pattern:
                return "Error: Pattern cannot be empty"
            
            # Resolve search path
            if path:
                is_safe, resolved_path = self._resolve_path(path)
                if not is_safe or resolved_path is None:
                    return f"Error: Path '{path}' is not readable (system/sensitive directory)"
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
        """List the contents of a directory.

        Use this for quick workspace exploration before reading files in detail.

        :param path: Optional directory to list. Defaults to the active workspace or
            primary base directory.
        :param limit: Maximum number of entries to return.
        :return: Directory entries sorted alphabetically, with ``/`` appended to
            directory names, or an error message. When too many entries exist, the
            result includes a listing-limited notice.
        """
        try:
            # Resolve path
            if path:
                is_safe, resolved_path = self._resolve_path(path)
                if not is_safe or resolved_path is None:
                    return f"Error: Path '{path}' is not readable (system/sensitive directory)"
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