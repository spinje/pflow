"""Shell node implementation for executing system commands."""

import base64
import logging
import os
import shutil
import signal
import subprocess
import sys
from contextlib import suppress
from pathlib import Path
from typing import Any, ClassVar

from pflow.core.node import Node
from pflow.core.user_errors import UserFriendlyError

logger = logging.getLogger(__name__)

# Default Git for Windows install locations, probed last by
# _resolve_windows_bash(). Module-level so tests can point the probes at
# temp paths without patching Path.is_file globally.
_GIT_BASH_DEFAULT_PATHS: tuple[str, ...] = (
    r"C:\Program Files\Git\bin\bash.exe",
    r"C:\Program Files (x86)\Git\bin\bash.exe",
)


def _git_bash_support_paths(bash_path: str) -> list[str]:
    """Return Git-for-Windows directories that make non-login bash useful.

    A clean end-user install often has ``Git\\cmd`` on PATH but not
    ``Git\\usr\\bin``. ``bash -c`` is non-login/non-interactive, so seed PATH
    from the resolved bash location instead of relying on profile startup.
    """
    path = Path(bash_path)
    candidates: list[Path] = []
    parent = path.parent

    if parent.name.lower() == "bin" and parent.parent.name.lower() == "usr":
        # C:\Program Files\Git\usr\bin\bash.exe
        candidates.append(parent.parent.parent)
    elif parent.name.lower() == "bin":
        # C:\Program Files\Git\bin\bash.exe
        candidates.append(parent.parent)

    roots: list[Path] = []
    for candidate in candidates:
        if candidate not in roots:
            roots.append(candidate)

    support_paths: list[str] = []
    for root in roots:
        for subdir in (root / "usr" / "bin", root / "bin"):
            if subdir.is_dir():
                support_paths.append(str(subdir))
    return support_paths


def _prepare_windows_shell_env(base_env: dict[str, str] | None, bash_path: str) -> dict[str, str]:
    """Prepare environment for Git Bash shell steps on Windows."""
    full_env = dict(os.environ if base_env is None else base_env)
    full_env.setdefault("MSYS_NO_PATHCONV", "1")

    support_paths = _git_bash_support_paths(bash_path)
    if support_paths:
        current_path = full_env.get("PATH", "")
        full_env["PATH"] = os.pathsep.join([*support_paths, current_path] if current_path else support_paths)
    return full_env


def _windows_path_to_bash(path_text: str) -> str:
    drive = path_text[0].lower()
    tail = path_text[2:].replace("\\", "/")
    return f"/{drive}{tail}"


def _translate_windows_paths_for_bash(command: str) -> str:
    """Translate native absolute Windows paths embedded in POSIX shell commands.

    The shell dialect is POSIX sh, but pflow's Python-side path values are
    native Windows strings. Without this bridge, command templates like
    ``cat C:\\Users\\...\\flag.txt`` are parsed by bash as ``C:Users...`` because
    backslashes are escape characters. The translation is intentionally narrow:
    drive-letter absolute paths without shell metacharacters.
    """
    import re

    quoted_pattern = re.compile(r"(?P<quote>['\"])(?P<path>[A-Za-z]:[\\/][^'\"]+)(?P=quote)")
    command = quoted_pattern.sub(
        lambda match: f"{match.group('quote')}{_windows_path_to_bash(match.group('path'))}{match.group('quote')}",
        command,
    )

    unquoted_pattern = re.compile(r"(?<![A-Za-z0-9_/-])([A-Za-z]:[\\/][^\s'\"|;&<>()`$]+)")
    return unquoted_pattern.sub(lambda match: _windows_path_to_bash(match.group(1)), command)


def _is_simple_which_probe(command: str) -> bool:
    """Whether ``command`` is only a ``which`` lookup, not a compound shell form."""
    stripped = command.strip()
    if not stripped.startswith("which "):
        return False
    return not any(token in stripped for token in ("|", ";", "&", "<", ">", "\n", "(", ")", "`", "$("))


def _terminate_windows_process_tree(pid: int) -> None:
    """Best-effort termination for Git Bash and any child process it spawned."""
    taskkill_path = shutil.which("taskkill") or r"C:\Windows\System32\taskkill.exe"
    try:
        result = subprocess.run(
            [taskkill_path, "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return
    if result.returncode != 0:
        logger.debug("taskkill failed while terminating shell process tree", extra={"pid": pid})


def _run_windows_bash_command(
    bash_path: str,
    command: str,
    *,
    stdin_bytes: bytes | None,
    cwd: str | None,
    env: dict[str, str],
    timeout: int | float,
) -> subprocess.CompletedProcess[bytes]:
    """Run a Git Bash command with timeout semantics that kill child processes.

    On Windows, ``subprocess.run(timeout=...)`` kills only the bash process.
    Children such as ``sleep`` can keep inherited pipe handles open, causing
    communicate() to wait until the child exits. Killing the process tree keeps
    shell-node timeout behavior consistent with POSIX.
    """
    argv = [bash_path, "-c", _translate_windows_paths_for_bash(command)]
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    proc = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.PIPE if stdin_bytes is not None else None,
        cwd=cwd,
        env=env,
        creationflags=creationflags,
    )
    try:
        stdout, stderr = proc.communicate(input=stdin_bytes, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        _terminate_windows_process_tree(proc.pid)
        with suppress(OSError):
            proc.kill()
        try:
            stdout, stderr = proc.communicate(timeout=1)
        except (OSError, subprocess.TimeoutExpired):
            stdout = exc.output or b""
            stderr = exc.stderr or b""
        raise subprocess.TimeoutExpired(
            argv, timeout, output=stdout or exc.output, stderr=stderr or exc.stderr
        ) from exc
    except (KeyboardInterrupt, SystemExit):
        _terminate_windows_process_tree(proc.pid)
        with suppress(OSError):
            proc.kill()
        with suppress(OSError, subprocess.TimeoutExpired):
            proc.communicate(timeout=1)
        raise
    return subprocess.CompletedProcess(argv, proc.returncode, stdout, stderr)


def _run_posix_shell_command(
    command: str,
    *,
    stdin_bytes: bytes | None,
    cwd: str | None,
    env: dict[str, str] | None,
    timeout: int | float,
) -> subprocess.CompletedProcess[bytes]:
    """Run a POSIX shell command with timeout semantics that kill child processes."""

    def terminate_process_group(proc: "subprocess.Popen[bytes]") -> None:
        killpg = getattr(os, "killpg", None)
        getpgid = getattr(os, "getpgid", None)
        if killpg is not None and getpgid is not None:
            with suppress(OSError):
                killpg(getpgid(proc.pid), getattr(signal, "SIGKILL", signal.SIGTERM))
        with suppress(OSError):
            proc.kill()

    proc = subprocess.Popen(
        command,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.PIPE if stdin_bytes is not None else None,
        cwd=cwd,
        env=env,
        # Give the shell its own process group so timeout and Ctrl-C/SystemExit
        # cleanup can kill grandchildren that inherited stdout/stderr pipes.
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(input=stdin_bytes, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        terminate_process_group(proc)
        try:
            stdout, stderr = proc.communicate(timeout=1)
        except (OSError, subprocess.TimeoutExpired):
            stdout = exc.output or b""
            stderr = exc.stderr or b""
        raise subprocess.TimeoutExpired(
            command, timeout, output=stdout or exc.output, stderr=stderr or exc.stderr
        ) from exc
    except (KeyboardInterrupt, SystemExit):
        terminate_process_group(proc)
        with suppress(OSError, subprocess.TimeoutExpired):
            proc.communicate(timeout=1)
        raise
    return subprocess.CompletedProcess(command, proc.returncode, stdout, stderr)


def _resolve_windows_bash() -> str | None:
    """Resolve a Git Bash executable on Windows (ADR-0013).

    Shell steps mean POSIX sh on every platform; on win32 that shell is
    supplied by Git Bash, resolved deliberately — never a naive
    ``which("bash")``, because on end-user machines that can be the WSL
    launcher (``C:\\Windows\\System32\\bash.exe``), a separate Linux VM with
    a different filesystem. CI can't catch that trap (runners put Git Bash
    on PATH), so only the explicit rejection below protects real machines.

    Resolution order:
    1. ``PFLOW_BASH`` env var — trusted verbatim, not validated: the user set
       it deliberately, and a wrong path produces a subprocess error naming
       that path. Empty string counts as unset.
    2. ``bash`` on PATH, rejected if it resolves under System32 (WSL trap).
    3. Derived from the Git install: ``{bin,usr/bin}/bash.exe`` probed under
       both the parent and grandparent of git.exe's directory — covers
       git.exe resolving from ``Git\\cmd``, ``Git\\bin``, and
       ``Git\\mingw64\\bin``.
    4. Default Git for Windows install locations.

    Deliberately uncached: a cached None would go stale in the long-lived MCP
    server after the user installs Git, and a cache would cross-contaminate
    tests that mock shutil.which. Resolution costs microseconds, once per
    shell step.

    Returns:
        Absolute path to bash.exe, or None when no Git Bash could be found.
    """
    override = os.environ.get("PFLOW_BASH")
    if override:
        return override

    on_path = shutil.which("bash")
    if on_path and "system32" not in on_path.lower():
        return on_path

    git = shutil.which("git")
    if git:
        git_dir = Path(git).parent
        for root in (git_dir.parent, git_dir.parent.parent):
            for candidate in (root / "bin" / "bash.exe", root / "usr" / "bin" / "bash.exe"):
                if candidate.is_file():
                    return str(candidate)

    for default in _GIT_BASH_DEFAULT_PATHS:
        if Path(default).is_file():
            return default

    return None


def _windows_bash_or_raise() -> str | None:
    """Resolve the win32 POSIX shell for prep(), or raise install guidance.

    Called from prep() and ONLY prep() — never exec(): exec_fallback()
    converts every exec() raise into {exit_code: -2} without re-raising, and
    post() then returns the SUCCESS action under ignore_errors: true — a
    missing bash raised from exec() would become a silent green run with
    empty stdout. prep() runs outside any try/except (core/node.py _run), so
    a raise here reaches the diagnostic pipeline intact and is immune to
    ignore_errors.

    Returns:
        Path to bash.exe on win32; None on every other platform.

    Raises:
        UserFriendlyError: On win32 when no Git Bash can be resolved.
    """
    if sys.platform != "win32":
        return None

    bash_path = _resolve_windows_bash()
    if bash_path is None:
        raise UserFriendlyError(
            title="Shell steps need a POSIX shell, and none was found on this Windows system",
            explanation=(
                "pflow runs shell steps with POSIX shell semantics on every platform "
                "so workflows behave identically everywhere. On Windows that shell is "
                "provided by Git Bash, which could not be found (checked PATH, the Git "
                "installation, and the default install locations)."
            ),
            suggestions=[
                "Install Git for Windows from https://gitforwindows.org (includes Git Bash)",
                "If bash is installed somewhere unusual, set the PFLOW_BASH environment "
                'variable to its full path, e.g. PFLOW_BASH="C:\\Program Files\\Git\\bin\\bash.exe"',
            ],
            technical_details=(
                "WSL bash (C:\\Windows\\System32\\bash.exe) is deliberately not used: it "
                "executes inside a separate Linux VM with a different filesystem. See ADR-0013."
            ),
        )
    return bash_path


class ShellNode(Node):
    """
    Execute shell commands with full Unix power.

    Shell dialect contract (ADR-0013): a shell step means POSIX sh semantics
    on EVERY platform. On Unix, commands run via shell=True (/bin/sh); on
    Windows they run through Git Bash (["bash", "-c", command], resolved by
    _resolve_windows_bash) — never cmd.exe or PowerShell, so one command
    string means the same thing everywhere. Windows without Git for Windows
    gets a structured install-guidance error, not a different dialect.
    Native dialects, if ever wanted, must arrive as additive opt-in
    per-step parameters — never by changing what an unadorned step means.

    WARNING: This node executes commands through a full shell for maximum
    compatibility with pipes, redirects, and shell constructs. Only run
    trusted commands.

    Security features:
    - Blocks obviously dangerous patterns (rm -rf /, fork bombs, device writes)
    - Warns on sudo/shutdown/reboot commands (blocks in strict mode)
    - Set PFLOW_SHELL_STRICT=true to block warning patterns
    - Audit logs all executed commands for security review

    Smart Error Handling:
    The shell node automatically treats certain non-zero exits as success:
    - ls with glob patterns that match no files (e.g., ls *.txt)
    - grep/rg that find no matches
    - which/command -v/type checking for non-existent commands
    - find returning no results

    These are treated as empty results, not errors. Use ignore_errors=true
    for other cases where you want to continue despite failures.

    Template Variables and Data Handling:

    The shell node supports template variables in both command and stdin parameters,
    but they serve different purposes:

    ✅ CORRECT - Use stdin for data (JSON, large text, complex strings):
      {
        "stdin": "${upstream.result}",           # Data with quotes, special chars, etc.
        "command": "jq -r '.data.field'"         # Processing logic
      }

      Why stdin?
      - No shell escaping issues (data is piped, not interpreted)
      - Handles any data: JSON, binary, special characters, newlines
      - Follows Unix philosophy: data via stdin, logic in command
      - More reliable and maintainable

    💡 Nested Template Access (MCP JSON Parsing Feature):
      MCP and HTTP nodes return parsed JSON. You can access nested properties
      in template variables: ${node.result.data.field}

      ⚠️ CRITICAL: Where you use nested access matters!

      ✅ In stdin - Always safe (any data type):
        {
          "stdin": "${api.response.items}",        # Array/object - safe in stdin
          "command": "jq -c 'map(.name)'"
        }
        {
          "stdin": "${api.response.data.values}",  # Complex nested - safe
          "command": "jq 'length'"
        }
        # Works because stdin bypasses shell parsing - data is piped directly

      ✅ In commands - Safe for simple scalars only:
        {
          "command": "echo User ID: ${user.profile.id}"        # Number - safe
        }
        {
          "command": "curl ${api.response.next_url}"           # URL string - safe
        }
        {
          "command": "ls ${config.settings.directory}"         # Path string - safe
        }
        # Safe because simple values don't contain shell special characters

      ❌ In commands - Never use complex data:
        {
          "command": "echo '${api.response.items}' | jq"       # Array - BREAKS!
        }
        {
          "command": "cat <<< '${mcp.result.data}' | jq"       # Object - BREAKS!
        }
        # Fails with shell escaping if data contains ( ) ' " [ ] etc.

      🎯 Rule: stdin = data (any type), command = logic (scalars only)
         Nested access works everywhere, but complex data needs stdin.

    Pattern Detection:
    The shell node will detect when you try to use structured data (dict/list) in
    command templates and error with a helpful message guiding you to use stdin instead.

    Interface:
    - Params: stdin: any  # Optional input data for the command (dict/list auto-serialized to JSON)
    - Writes: shared["stdout"]: str  # Command standard output (text or base64-encoded binary)
    - Writes: shared["stdout_is_binary"]: bool  # True if stdout is binary data
    - Writes: shared["stderr"]: str  # Command error output (text or base64-encoded binary)
    - Writes: shared["stderr_is_binary"]: bool  # True if stderr is binary data
    - Writes: shared["exit_code"]: int  # Process exit code
    - Params: command: str  # Shell command to execute (required)
    - Params: cwd: str  # Working directory (optional, defaults to current)
    - Params: env: dict  # Additional environment variables (optional)
    - Params: timeout: int  # Max execution time in seconds (optional, default 30)
    - Params: ignore_errors: bool  # Continue on non-zero exit (optional, default false)
    - Params: strip_newline: bool  # Strip trailing newlines from stdout only (optional, default true). stderr is never stripped.
    - Actions: default (exit code 0 or ignore_errors=true or auto-handled), error (non-zero exit or timeout)

    IMPORTANT: The shell node returns "error" action on command failure. If your workflow
    doesn't define error edges, use ignore_errors=true to continue on failures.
    """

    # Basic patterns for obviously dangerous commands
    # This is NOT comprehensive security - just a basic safety net
    DANGEROUS_PATTERNS: ClassVar[list[str]] = [
        # Recursive deletions of system root
        "rm -rf /",
        "rm -rf /*",
        "rm -fr /",
        "rm -f -r /",
        "rm / -rf",
        "rm /* -rf",
        # Device operations that could destroy data
        "dd if=/dev/zero of=/dev/",
        "dd if=/dev/random of=/dev/",
        "dd if=/dev/urandom of=/dev/",
        "> /dev/sd",
        "> /dev/hd",
        "> /dev/nvme",
        "mkfs.",
        "format C:",
        "format c:",
        # Fork bombs and resource exhaustion
        ":(){ :|:& };:",
        "fork while fork",
        # System-wide permission changes
        "chmod -R 777 /",
        "chmod 777 /",
        "chown -R",
        # Privilege escalation with dangerous commands
        "sudo rm -rf /",
        "sudo rm -rf /*",
        'su -c "rm -rf /',
    ]

    # Additional warning patterns (logged but not blocked)
    WARNING_PATTERNS: ClassVar[list[str]] = [
        "sudo ",
        "su -",
        "shutdown",
        "reboot",
        "halt",
        "init 0",
        "init 6",
        "systemctl poweroff",
    ]

    DEFAULT_TIMEOUT = 30  # seconds

    def _is_safe_non_error(self, command: str, exit_code: int, stdout: str, stderr: str) -> tuple[bool, str]:
        """Check if a non-zero exit code is actually a safe "no results" case.

        Determines if commands like grep, find, or diff returned non-zero because
        they legitimately found no results, rather than due to an actual error.

        IMPORTANT: For most patterns (grep, rg, which, command -v), we only treat
        exit code as "safe" if stderr is EMPTY. If stderr has content, it likely
        indicates a real error from a downstream command in a pipeline, not a
        legitimate "no results" case. This prevents silent failures in pipelines
        like `grep pattern | sed 's/bad_regex/'` where sed fails but grep is blamed.

        IMPORTANT: Only call this for TEXT output. Binary output should skip this
        check entirely since safe patterns ("No such file", "not found", "no matches")
        don't apply to binary data. Calling this on binary output could cause:
        1. False positives from random bytes matching patterns
        2. UnicodeDecodeError if binary data interpreted as text
        3. Incorrect auto-handling of legitimate binary command failures

        Binary detection happens in exec() and is checked in post() before calling
        this method (see lines 616-622).

        Args:
            command: The shell command that was executed
            exit_code: The non-zero exit code returned
            stdout: Command stdout (must be text, not base64 or binary)
            stderr: Command stderr (must be text, not base64 or binary)

        Returns:
            Tuple of (is_safe, reason) where:
            - is_safe: True if this is a safe non-error (e.g., grep no match)
            - reason: Human-readable explanation of why it's safe (for logging)

        IMPORTANT: When adding new patterns here, the reason string MUST contain
        either "no matches" or "not found" for proper tag display in CLI output.
        See src/pflow/core/output_controller.py _handle_node_complete() for the
        tag mapping. If neither phrase fits your pattern, the raw reason is
        shown as-is as a yellow tag so agents can still diagnose the case.
        """
        # Check if stderr has content - this usually indicates a real error
        # from a command in the pipeline, not a "no results" case
        has_stderr_content = stderr and stderr.strip()

        # ls with glob patterns that match no files
        # Note: ls explicitly checks for specific stderr messages, so it's different
        if (
            exit_code != 0
            and command.strip().startswith("ls ")
            and any(char in command for char in ["*", "?", "[", "]"])
            and ("No such file or directory" in stderr or "cannot access" in stderr)
        ):
            return True, "ls with glob pattern - no matches"

        # grep returns 1 when pattern not found (this is normal behavior)
        # BUT only if stderr is empty - otherwise a downstream command likely failed
        if (
            exit_code == 1
            and not has_stderr_content
            and (
                command.strip().startswith("grep ")
                or " grep " in command
                or "|grep " in command
                or "| grep " in command
            )
        ):
            return True, "grep exit 1 with empty stderr - no matches"

        # ripgrep (rg) returns 1 when pattern not found
        # BUT only if stderr is empty - otherwise a downstream command likely failed
        if (
            exit_code == 1
            and not has_stderr_content
            and (command.strip().startswith("rg ") or " rg " in command or "|rg " in command or "| rg " in command)
        ):
            return True, "ripgrep exit 1 with empty stderr - no matches"

        # which returns non-zero when command doesn't exist (that's its purpose).
        # Keep this to a simple command so pipeline/downstream failures still surface.
        stripped_command = command.strip()
        if exit_code != 0 and _is_simple_which_probe(stripped_command):
            return True, "which exit non-zero - command not found"

        # command -v returns 1 when command doesn't exist
        # BUT only if stderr is empty - otherwise a downstream command likely failed
        if exit_code != 0 and not has_stderr_content and "command -v" in command:
            return True, "command -v exit 1 with empty stderr - command not found"

        # type returns 1 when command not found
        # "not found" appears in stdout on some systems (bash), stderr on others
        # If stderr has content beyond "not found", it's likely a downstream error
        type_not_found = "not found" in stderr or "not found" in stdout
        stderr_has_other_errors = has_stderr_content and "not found" not in stderr
        if exit_code != 0 and command.strip().startswith("type ") and type_not_found and not stderr_has_other_errors:
            return True, "type exit 1 - command not found"

        # find with no results (returns 0 but empty output)
        if exit_code == 0 and command.strip().startswith("find ") and not stdout.strip():
            # This is actually already success (exit 0), but documenting the pattern
            return False, ""

        return False, ""

    def _normalize_exit_code_for_safe_patterns(self, command: str, exit_code: int, stdout: str, stderr: str) -> int:
        """Normalize exit codes for known safe patterns to be consistent across platforms.

        Some environments (e.g., macOS vs GNU coreutils) return different non-zero codes
        for the same "no results" scenarios. We standardize these to 1 for predictability
        in tests and downstream logic.

        Note: This function should only be called when _is_safe_non_error returns True,
        so the stderr checks are already done there. We keep the same logic here for
        consistency and safety.
        """
        # Handle bytes (binary output) - can't do pattern matching on bytes
        if isinstance(stderr, bytes) or isinstance(stdout, bytes):
            return exit_code

        has_stderr_content = stderr and stderr.strip()

        # Normalize ls glob no-match to 1
        if (
            exit_code != 0
            and command.strip().startswith("ls ")
            and any(char in command for char in ["*", "?", "[", "]"])
            and ("No such file or directory" in stderr or "cannot access" in stderr)
        ):
            return 1
        # Normalize simple which not-found to 1.
        stripped_command = command.strip()
        if exit_code != 0 and _is_simple_which_probe(stripped_command):
            return 1
        # Normalize command -v not-found to 1 (only if no stderr content)
        if exit_code != 0 and not has_stderr_content and "command -v" in command:
            return 1
        # Normalize type not-found to 1 (only if no other stderr errors)
        type_not_found = "not found" in stderr or "not found" in stdout
        stderr_has_other_errors = has_stderr_content and "not found" not in stderr
        if exit_code != 0 and command.strip().startswith("type ") and type_not_found and not stderr_has_other_errors:
            return 1
        return exit_code

    def _adapt_stdin_to_string(self, stdin: Any) -> str | None:
        """Adapt any type to string suitable for subprocess stdin.

        The shell node accepts template variables of any type but subprocess
        requires string or None for stdin. This method intelligently converts
        types to strings suitable for shell processing.

        Conversion rules:
        - str: Use as-is (already correct)
        - None: Keep as None (means "no input")
        - dict/list: Serialize to JSON (common case: piping to jq, python, etc.)
        - int/float/bool: Convert to string representation
        - bytes: Decode to UTF-8 (with latin-1 fallback)
        - Other: Fallback to str() for custom objects

        Args:
            stdin: Value from template resolution (can be any Python type)

        Returns:
            String suitable for subprocess stdin, or None for no input
        """
        import json

        if stdin is None:
            return None

        if isinstance(stdin, str):
            return stdin

        if isinstance(stdin, (dict, list)):
            # Common case: JSON data for pipes (jq, python -m json.tool, etc.)
            try:
                result = json.dumps(stdin, ensure_ascii=False)
                logger.info(
                    f"Serialized {type(stdin).__name__} to JSON for stdin",
                    extra={"phase": "prep", "type": type(stdin).__name__, "size": len(stdin)},
                )
                return result
            except (TypeError, ValueError) as e:
                # Fallback if JSON serialization fails (e.g., unserializable objects)
                logger.warning(
                    f"Failed to serialize {type(stdin).__name__} to JSON, using str() fallback",
                    extra={"phase": "prep", "error": str(e)},
                )
                return str(stdin)

        if isinstance(stdin, bytes):
            # Decode bytes to string
            try:
                result = stdin.decode("utf-8")
                logger.debug("Decoded bytes to UTF-8 for stdin", extra={"phase": "prep"})
                return result
            except UnicodeDecodeError:
                # Try latin-1 as fallback (accepts all byte values)
                result = stdin.decode("latin-1")
                logger.debug("Decoded bytes to latin-1 for stdin", extra={"phase": "prep"})
                return result

        if isinstance(stdin, bool):
            # Use lowercase for CLI/JSON compatibility
            # Many tools (jq, JSON parsers, CLI flags) expect lowercase "true"/"false"
            result = "true" if stdin else "false"
            logger.debug(
                f"Converted bool to lowercase string for stdin: {result}",
                extra={"phase": "prep", "value": result},
            )
            return result

        # int, float, or custom objects
        result = str(stdin)
        logger.debug(
            f"Converted {type(stdin).__name__} to string for stdin",
            extra={"phase": "prep", "type": type(stdin).__name__, "value": str(result)[:100]},
        )
        return result

    @staticmethod
    def _build_shell_error_message(exit_code: int, stderr: str) -> str:
        """Build a descriptive error message for shell command failures.

        Args:
            exit_code: The command's exit code
            stderr: The stderr output from the command

        Returns:
            A formatted error message with exit code and stderr preview
        """
        stderr_preview = stderr[:500] if stderr else ""
        error_msg = f"Command failed with exit code {exit_code}"
        if stderr_preview:
            error_msg += f": {stderr_preview}"
        return error_msg

    def _store_output(self, shared: dict, key: str, value: str | bytes, is_binary: bool, strip_newline: bool) -> None:
        """Store stdout/stderr in shared store with appropriate encoding.

        Args:
            shared: The shared store to write to
            key: Key name ("stdout" or "stderr")
            value: The output value (str for text, bytes for binary)
            is_binary: Whether the output is binary
            strip_newline: Whether to strip trailing newlines (stdout text only, ignored for binary)
        """
        if is_binary:
            # Binary data: encode as base64 (value is bytes when is_binary=True)
            binary_value = value if isinstance(value, bytes) else value.encode("utf-8")
            encoded = base64.b64encode(binary_value).decode("ascii")
            shared[key] = encoded
            shared[f"{key}_is_binary"] = True
        else:
            # Text data: optionally strip trailing newlines (value is str when is_binary=False)
            text_value = value if isinstance(value, str) else value.decode("utf-8")
            if strip_newline:
                text_value = text_value.rstrip("\n")
            shared[key] = text_value
            shared[f"{key}_is_binary"] = False

    def __init__(self) -> None:
        """Initialize the shell node with retry support."""
        # Shell commands can be flaky, so allow retries
        super().__init__(max_retries=1, wait=0)

    def prep(self, shared: dict) -> dict[str, Any]:
        """Prepare the command and configuration for execution.

        Args:
            shared: The shared store containing input data

        Returns:
            Dictionary with command configuration

        Raises:
            ValueError: If command is missing or dangerous
            UserFriendlyError: On Windows when no Git Bash can be resolved (ADR-0013)
        """
        # Get command from params (required)
        command = self.params.get("command")
        if not command:
            raise ValueError("Missing required 'command' parameter")

        # Check for obviously dangerous patterns
        command_lower = command.lower()
        for pattern in self.DANGEROUS_PATTERNS:
            if pattern.lower() in command_lower:
                raise ValueError(f"Dangerous command pattern detected: {pattern}")

        # Check for warning patterns (log but don't block unless strict mode)
        strict_mode = os.environ.get("PFLOW_SHELL_STRICT", "").lower() == "true"
        for pattern in self.WARNING_PATTERNS:
            if pattern.lower() in command_lower:
                if strict_mode:
                    raise ValueError(f"Command blocked in strict mode: {pattern}")
                else:
                    logger.warning(
                        f"Potentially dangerous command detected: {command[:50]}...",
                        extra={"pattern": pattern, "phase": "prep"},
                    )
                break  # Only log once per command

        # Get optional stdin from params
        stdin = self.params.get("stdin")

        # Adapt stdin to string (handle any type from templates)
        stdin = self._adapt_stdin_to_string(stdin)

        # Get optional configuration from params
        cwd = self.params.get("cwd")
        env = self.params.get("env", {})
        timeout = self.params.get("timeout", self.DEFAULT_TIMEOUT)
        ignore_errors = self.params.get("ignore_errors", False)
        strip_newline = self.params.get("strip_newline", True)

        # Validate and normalize working directory if provided
        if cwd:
            cwd = os.path.expanduser(cwd)
            cwd = os.path.abspath(cwd)
            cwd = os.path.normpath(cwd)

            if not os.path.isdir(cwd):
                raise ValueError(f"Working directory does not exist: {cwd}")

        # Validate timeout
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError(f"Invalid timeout value: {timeout}")

        # Resolve the POSIX shell on Windows (ADR-0013). Must happen in prep,
        # not exec — see _windows_bash_or_raise for why moving it breaks
        # error reporting under ignore_errors.
        bash_path = _windows_bash_or_raise()

        # Audit log all commands (useful for debugging and security reviews)
        logger.info(
            f"[AUDIT] Preparing command: {command[:100]}{'...' if len(command) > 100 else ''}",
            extra={
                "phase": "prep",
                "cwd": cwd,
                "timeout": timeout,
                "strict_mode": strict_mode,
                "audit": True,  # Mark as audit log for filtering
            },
        )

        return {
            "command": command,
            "stdin": stdin,
            "cwd": cwd,
            "env": env,
            "timeout": timeout,
            "ignore_errors": ignore_errors,
            "strip_newline": strip_newline,
            "bash_path": bash_path,
        }

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        """Execute the shell command.

        Args:
            prep_res: Prepared command configuration

        Returns:
            Dictionary with execution results
        """
        command = prep_res["command"]
        stdin = prep_res["stdin"]
        cwd = prep_res["cwd"]
        env = prep_res["env"]
        timeout = prep_res["timeout"]

        # Merge current environment with custom environment variables
        full_env = {**os.environ, **env} if env else None

        logger.debug(
            f"Executing command: {command[:100]}{'...' if len(command) > 100 else ''}",
            extra={"phase": "exec", "cwd": cwd},
        )

        try:
            # Encode stdin to bytes for text=False mode
            stdin_bytes = stdin.encode("utf-8") if stdin else None

            if sys.platform == "win32":
                # ADR-0013: POSIX sh everywhere — on Windows the command runs
                # through Git Bash (resolved in prep()), never cmd.exe, so one
                # shell dialect works on every platform.
                bash_path = prep_res["bash_path"]
                result = _run_windows_bash_command(
                    bash_path,
                    command,
                    stdin_bytes=stdin_bytes,
                    cwd=cwd,
                    env=_prepare_windows_shell_env(full_env, bash_path),
                    timeout=timeout,
                )
            else:
                # Execute the command with shell=True for full shell power
                # Security: shell=True is intentional - this is a shell node that provides full shell access
                result = _run_posix_shell_command(
                    command,
                    stdin_bytes=stdin_bytes,
                    cwd=cwd,
                    env=full_env,
                    timeout=timeout,
                )

            logger.info(
                f"[AUDIT] Command completed with exit code {result.returncode}",
                extra={"phase": "exec", "exit_code": result.returncode, "command": command[:100], "audit": True},
            )

            # Handle stdout - try decode, fallback to binary
            stdout: str | bytes
            try:
                stdout = result.stdout.decode("utf-8")
                stdout_is_binary = False
            except UnicodeDecodeError:
                # Binary output - keep as bytes for post() to encode
                stdout = result.stdout
                stdout_is_binary = True

            # Handle stderr - try decode, fallback to binary
            stderr: str | bytes
            try:
                stderr = result.stderr.decode("utf-8")
                stderr_is_binary = False
            except UnicodeDecodeError:
                # Binary error output
                stderr = result.stderr
                stderr_is_binary = True

            return {
                "stdout": stdout,
                "stdout_is_binary": stdout_is_binary,
                "stderr": stderr,
                "stderr_is_binary": stderr_is_binary,
                "exit_code": result.returncode,
                "timeout": False,
            }

        except subprocess.TimeoutExpired as e:
            logger.warning(f"Command timed out after {timeout} seconds", extra={"phase": "exec", "timeout": timeout})

            # Try to capture any partial output (with lossy decode for readability)
            stdout = e.stdout.decode("utf-8", errors="replace") if e.stdout else ""
            stderr = e.stderr.decode("utf-8", errors="replace") if e.stderr else ""

            return {
                "stdout": stdout,
                "stdout_is_binary": False,  # Lossy decode means treat as text
                "stderr": stderr,
                "stderr_is_binary": False,
                "exit_code": -1,  # Convention for timeout
                "timeout": True,
                "error": f"Command timed out after {timeout} seconds",
            }

        except Exception as e:
            logger.exception("Command execution failed", extra={"phase": "exec", "error": str(e)})
            raise

    def post(self, shared: dict, prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
        """Store results in shared store and determine action.

        Args:
            shared: The shared store to write results to
            prep_res: Prepared command configuration
            exec_res: Execution results

        Returns:
            Action string for flow control
        """
        # Handle stdout encoding (strip trailing newlines for text output)
        self._store_output(
            shared,
            "stdout",
            exec_res["stdout"],
            exec_res.get("stdout_is_binary", False),
            strip_newline=prep_res.get("strip_newline", True),
        )

        # Handle stderr encoding (never strip newlines)
        self._store_output(
            shared,
            "stderr",
            exec_res["stderr"],
            exec_res.get("stderr_is_binary", False),
            strip_newline=False,
        )

        # Store exit code
        shared["exit_code"] = exec_res["exit_code"]

        # Store command for error reporting
        shared["command"] = prep_res["command"]

        # Store error message if present
        if "error" in exec_res:
            shared["error"] = exec_res["error"]

        # Determine action based on exit code and configuration
        ignore_errors = prep_res["ignore_errors"]
        exit_code = exec_res["exit_code"]
        timeout = exec_res.get("timeout", False)

        if timeout:
            return "error"

        if exit_code == 0:
            logger.info("Command succeeded", extra={"phase": "post"})
            return "default"  # PocketFlow standard success action

        if ignore_errors:
            # For ignore_errors=true, normalize common benign cases to exit_code 1
            command = prep_res["command"]
            stdout = exec_res["stdout"]
            stderr = exec_res["stderr"]
            normalized_exit = self._normalize_exit_code_for_safe_patterns(command, exit_code, stdout, stderr)
            shared["exit_code"] = normalized_exit
            logger.info(
                f"Command failed with exit code {exit_code} but continuing (ignore_errors=true)",
                extra={"phase": "post", "exit_code": normalized_exit},
            )
            return "default"  # Continue on normal path

        # Check if this is a safe "no results" pattern that shouldn't be treated as an error
        # Note: Only check safe patterns for text output (binary commands don't have these patterns)
        command = prep_res["command"]
        stdout = exec_res["stdout"]
        stderr = exec_res["stderr"]

        # Skip safe pattern check if output is binary
        if exec_res.get("stdout_is_binary", False) or exec_res.get("stderr_is_binary", False):
            # Binary output - safe pattern detection doesn't apply
            is_safe = False
            reason = ""
        else:
            # Text output - check safe patterns
            is_safe, reason = self._is_safe_non_error(command, exit_code, stdout, stderr)
        if is_safe:
            # Normalize exit codes across platforms for predictable behavior
            normalized_exit = self._normalize_exit_code_for_safe_patterns(command, exit_code, stdout, stderr)
            shared_exit = normalized_exit if isinstance(normalized_exit, int) else exit_code
            # Reflect normalized code back into shared for test expectations
            shared["exit_code"] = shared_exit
            # Store smart handling info for visibility in execution summary
            shared["smart_handled"] = True
            shared["smart_handled_reason"] = reason
            # Ensure stderr contains a helpful message for type-not-found across platforms
            if (
                command.strip().startswith("type ")
                and "not found" not in (shared.get("stderr") or "")
                and "not found" in (stdout or "")
            ):
                # Mirror message from stdout to stderr for cross-platform consistency
                shared["stderr"] = stdout
            logger.info(
                f"Auto-handling non-error: {reason}",
                extra={
                    "phase": "post",
                    "exit_code": shared_exit,
                    "auto_handled": True,
                    "command": command[:100] + "..." if len(command) > 100 else command,
                },
            )
            return "default"  # Continue on normal path

        # Build descriptive error message for non-zero exit codes
        shared["error"] = self._build_shell_error_message(exit_code, shared.get("stderr", ""))

        # Intentionally no logger.warning here — pflow's diagnostic pipeline
        # already surfaces this exact message via call_completion_callback
        # (which builds "Command failed with exit code N" from
        # shared["exit_code"]) and via the post-execution diagnostic block.
        # Logging it here would write directly to stderr and corrupt the
        # live progress callback's partial `node_id...` line.
        return "error"

    def exec_fallback(self, prep_res: dict[str, Any], exc: Exception) -> dict[str, Any]:
        """Handle execution failures gracefully.

        Args:
            prep_res: Prepared command configuration
            exc: The exception that occurred

        Returns:
            Dictionary with error information
        """
        command = prep_res["command"]
        logger.error(f"Command execution failed: {exc}", extra={"phase": "fallback", "command": command[:100]})

        return {
            "stdout": "",
            "stderr": str(exc),
            "exit_code": -2,  # Convention for execution failure
            "error": f"Failed to execute command: {exc}",
        }
