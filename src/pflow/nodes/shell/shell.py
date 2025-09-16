"""Shell node implementation for executing system commands."""

import logging
import os
import subprocess
from typing import Any, ClassVar

from pocketflow import Node

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

    Interface:
    - Reads: shared["stdin"]: str  # Optional input data for the command
    - Writes: shared["stdout"]: str  # Command standard output
    - Writes: shared["stderr"]: str  # Command error output
    - Writes: shared["exit_code"]: int  # Process exit code
    - Params: command: str  # Shell command to execute (required)
    - Params: cwd: str  # Working directory (optional, defaults to current)
    - Params: env: dict  # Additional environment variables (optional)
    - Params: timeout: int  # Max execution time in seconds (optional, default 30)
    - Params: ignore_errors: bool  # Continue on non-zero exit (optional, default false)
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

        Returns:
            Tuple of (is_safe, reason) where is_safe indicates if this should be treated
            as success, and reason explains why (for logging).
        """
        # ls with glob patterns that match no files
        if (
            exit_code != 0
            and command.strip().startswith("ls ")
            and any(char in command for char in ["*", "?", "[", "]"])
            and ("No such file or directory" in stderr or "cannot access" in stderr)
        ):
            return True, "ls with glob pattern - empty matches are valid"

        # grep returns 1 when pattern not found (this is normal behavior)
        if exit_code == 1 and (
            command.strip().startswith("grep ") or " grep " in command or "|grep " in command or "| grep " in command
        ):
            return True, "grep returns 1 when pattern not found - valid result"

        # ripgrep (rg) returns 1 when pattern not found
        if exit_code == 1 and (
            command.strip().startswith("rg ") or " rg " in command or "|rg " in command or "| rg " in command
        ):
            return True, "ripgrep returns 1 when pattern not found - valid result"

        # which returns 1 when command doesn't exist (that's its purpose)
        if exit_code != 0 and command.strip().startswith("which "):
            return True, "which returns 1 when command doesn't exist - existence check"

        # command -v returns 1 when command doesn't exist
        if exit_code != 0 and "command -v" in command:
            return True, "command -v returns 1 when command doesn't exist - existence check"

        # type returns 1 when command not found
        if exit_code != 0 and command.strip().startswith("type ") and ("not found" in stderr or "not found" in stdout):
            return True, "type returns 1 when command not found - existence check"

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
        """
        # Normalize ls glob no-match to 1
        if (
            exit_code != 0
            and command.strip().startswith("ls ")
            and any(char in command for char in ["*", "?", "[", "]"])
            and ("No such file or directory" in stderr or "cannot access" in stderr)
        ):
            return 1
        # Normalize which not-found to 1
        if exit_code != 0 and command.strip().startswith("which "):
            return 1
        # Normalize command -v not-found to 1
        if exit_code != 0 and "command -v" in command:
            return 1
        # Normalize type not-found to 1
        if exit_code != 0 and command.strip().startswith("type ") and ("not found" in stderr or "not found" in stdout):
            return 1
        return exit_code

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

        # Get optional stdin from shared store
        stdin = shared.get("stdin")

        # Get optional configuration from params
        cwd = self.params.get("cwd")
        env = self.params.get("env", {})
        timeout = self.params.get("timeout", self.DEFAULT_TIMEOUT)
        ignore_errors = self.params.get("ignore_errors", False)

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
            # Execute the command with shell=True for full shell power
            # Security: shell=True is intentional - this is a shell node that provides full shell access
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True, input=stdin, cwd=cwd, env=full_env, timeout=timeout
            )

            logger.info(
                f"[AUDIT] Command completed with exit code {result.returncode}",
                extra={"phase": "exec", "exit_code": result.returncode, "command": command[:100], "audit": True},
            )

            return {"stdout": result.stdout, "stderr": result.stderr, "exit_code": result.returncode, "timeout": False}

        except subprocess.TimeoutExpired as e:
            logger.exception(f"Command timed out after {timeout} seconds", extra={"phase": "exec", "timeout": timeout})

            # Try to capture any partial output
            stdout = e.stdout.decode("utf-8", errors="replace") if e.stdout else ""
            stderr = e.stderr.decode("utf-8", errors="replace") if e.stderr else ""

            return {
                "stdout": stdout,
                "stderr": stderr,
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
        # Store all outputs in shared store
        shared["stdout"] = exec_res["stdout"]
        shared["stderr"] = exec_res["stderr"]
        shared["exit_code"] = exec_res["exit_code"]

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
        command = prep_res["command"]
        stdout = exec_res["stdout"]
        stderr = exec_res["stderr"]

        is_safe, reason = self._is_safe_non_error(command, exit_code, stdout, stderr)
        if is_safe:
            # Normalize exit codes across platforms for predictable behavior
            normalized_exit = self._normalize_exit_code_for_safe_patterns(command, exit_code, stdout, stderr)
            shared_exit = normalized_exit if isinstance(normalized_exit, int) else exit_code
            # Reflect normalized code back into shared for test expectations
            shared["exit_code"] = shared_exit
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
