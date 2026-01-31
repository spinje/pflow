"""Shell node implementation for executing system commands."""

import base64
import logging
import os
import subprocess
from typing import Any, ClassVar

from pflow.pocketflow import Node

logger = logging.getLogger(__name__)


class ShellNode(Node):
    """
    Execute shell commands with full Unix power.

    WARNING: This node executes commands with shell=True for maximum compatibility
    with pipes, redirects, and shell constructs. Only run trusted commands.

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
        See src/pflow/cli/main.py _format_node_status_line() for the tag mapping.
        If neither phrase fits your pattern, update the tag mapping in main.py.
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

        # which returns 1 when command doesn't exist (that's its purpose)
        # BUT only if stderr is empty - otherwise a downstream command likely failed
        if exit_code != 0 and not has_stderr_content and command.strip().startswith("which "):
            return True, "which exit 1 with empty stderr - command not found"

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
        # Normalize which not-found to 1 (only if no stderr content)
        if exit_code != 0 and not has_stderr_content and command.strip().startswith("which "):
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

            # Execute the command with shell=True for full shell power
            # Security: shell=True is intentional - this is a shell node that provides full shell access
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=False,
                input=stdin_bytes,
                cwd=cwd,
                env=full_env,
                timeout=timeout,
            )

            logger.info(
                f"[AUDIT] Command completed with exit code {result.returncode}",
                extra={"phase": "exec", "exit_code": result.returncode, "command": command[:100], "audit": True},
            )

            # Handle stdout - try decode, fallback to binary
            try:
                stdout = result.stdout.decode("utf-8")
                stdout_is_binary = False
            except UnicodeDecodeError:
                # Binary output - keep as bytes for post() to encode
                stdout = result.stdout
                stdout_is_binary = True

            # Handle stderr - try decode, fallback to binary
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
            logger.exception(f"Command timed out after {timeout} seconds", extra={"phase": "exec", "timeout": timeout})

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
            logger.warning("Command timed out", extra={"phase": "post"})
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

        logger.warning(
            f"Command failed with exit code {exit_code}",
            extra={"phase": "post", "exit_code": exit_code},
        )
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
