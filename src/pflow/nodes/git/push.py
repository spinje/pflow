"""Git push node implementation."""

import logging
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

# Add pocketflow to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from pocketflow import Node

# Set up logging
logger = logging.getLogger(__name__)


class GitPushNode(Node):
    """
    Push commits to remote repository.

    Interface:
    - Params: branch: str  # Branch to push (optional, default: HEAD)
    - Params: remote: str  # Remote name (optional, default: origin)
    - Params: working_directory: str  # Directory to run git commands (optional, default: current directory)
    - Writes: shared["push_result"]: dict  # Push operation results
        - success: bool  # Whether push succeeded
        - branch: str  # Branch that was pushed
        - remote: str  # Remote that was pushed to
    - Actions: default (always)

    Note:
        This node operates on the current working directory only.
        It cannot target remote repositories like GitHub nodes can.
    """

    def __init__(self) -> None:
        """Initialize with retry support for network issues."""
        super().__init__(max_retries=2, wait=1.0)

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        """Extract branch and remote from parameters."""
        # Get branch from params, default to HEAD
        branch = self.params.get("branch", "HEAD")

        # Get remote from params, default to origin
        remote = self.params.get("remote", "origin")

        # Get working directory from params, default to current directory
        cwd = self.params.get("working_directory", ".")
        cwd = Path(cwd).expanduser().resolve()

        logger.debug(
            "Preparing to push to remote",
            extra={"branch": branch, "remote": remote, "working_directory": str(cwd), "phase": "prep"},
        )

        return {"branch": branch, "remote": remote, "working_directory": str(cwd)}

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        """
        Push commits to remote repository.

        Returns:
            Dictionary with push results

        Raises:
            subprocess.CalledProcessError: If git command fails
            subprocess.TimeoutExpired: If command takes too long
        """
        branch = prep_res["branch"]
        remote = prep_res["remote"]
        cwd = prep_res["working_directory"]

        logger.info(
            "Pushing to remote repository",
            extra={"branch": branch, "remote": remote, "working_directory": cwd, "phase": "exec"},
        )

        # TODO: Future enhancement - add working_directory parameter
        # cwd = prep_res.get("working_directory", None)

        # Execute git push command
        push_cmd = ["git", "push", remote, branch]
        push_result = subprocess.run(  # noqa: S603
            push_cmd, cwd=cwd, capture_output=True, text=True, shell=False, timeout=30, check=False
        )

        # Check for specific errors
        if push_result.returncode != 0:
            stderr_lower = push_result.stderr.lower()
            stdout_lower = push_result.stdout.lower()
            combined_output = stderr_lower + stdout_lower

            if "not a git repository" in stderr_lower:
                raise ValueError(f"Directory '{cwd}' is not a git repository")
            elif "rejected" in combined_output:
                # Push was rejected (e.g., non-fast-forward)
                logger.warning(
                    "Push was rejected",
                    extra={"branch": branch, "remote": remote, "stderr": push_result.stderr, "phase": "exec"},
                )
                return {
                    "success": False,
                    "branch": branch,
                    "remote": remote,
                    "reason": "rejected",
                    "details": push_result.stderr,
                }
            else:
                # Other git errors
                raise subprocess.CalledProcessError(
                    push_result.returncode, push_result.args, output=push_result.stdout, stderr=push_result.stderr
                )

        # Success case
        logger.info(
            "Successfully pushed to remote",
            extra={"branch": branch, "remote": remote, "working_directory": cwd, "phase": "exec"},
        )

        return {
            "success": True,
            "branch": branch,
            "remote": remote,
            "reason": "pushed",
            "details": push_result.stdout if push_result.stdout else "Push completed successfully",
        }

    def exec_fallback(self, prep_res: dict[str, Any], exc: Exception) -> dict[str, Any]:
        """Handle final failure after all retries with user-friendly messages."""
        branch = prep_res["branch"]
        remote = prep_res["remote"]
        cwd = prep_res["working_directory"]

        logger.error(
            f"Failed to push to remote after {self.max_retries} retries",
            extra={
                "branch": branch,
                "remote": remote,
                "working_directory": cwd,
                "error": str(exc),
                "phase": "fallback",
            },
        )

        # Provide specific error messages based on exception type
        error_msg = ""
        if isinstance(exc, ValueError) and "not a git repository" in str(exc):
            error_msg = f"Error: Directory '{cwd}' is not a git repository. Please run this command from within a git repository."
        elif isinstance(exc, subprocess.TimeoutExpired):
            error_msg = "Error: Git push timed out after 30 seconds. This may be due to network issues or authentication problems."
        elif isinstance(exc, subprocess.CalledProcessError):
            stderr_msg = exc.stderr if exc.stderr else "Unknown error"
            # Check for common authentication/permission errors
            if "authentication" in stderr_msg.lower() or "permission" in stderr_msg.lower():
                error_msg = f"Error: Git push failed - authentication or permission issue. {stderr_msg}"
            elif "could not read from remote" in stderr_msg.lower():
                error_msg = (
                    f"Error: Could not connect to remote '{remote}'. Check your network connection and remote URL."
                )
            else:
                error_msg = f"Error: Git push failed with exit code {exc.returncode}. {stderr_msg}"
        elif isinstance(exc, FileNotFoundError):
            error_msg = "Error: Git is not installed or not available in PATH. Please install git and try again."
        else:
            error_msg = f"Error: Could not push to remote after {self.max_retries} retries. {exc!s}"

        # Return a result dict with the error message
        return {"success": False, "branch": branch, "remote": remote, "reason": "error", "details": error_msg}

    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> Optional[str]:
        """Update shared store with push results and return action."""
        # Check for error first
        if not exec_res.get("success") and exec_res.get("reason") == "error":
            shared["error"] = exec_res.get("details", "Git push failed")
            shared["push_result"] = {
                "success": False,
                "branch": exec_res.get("branch", ""),
                "remote": exec_res.get("remote", ""),
            }
            logger.warning(
                "Push operation failed",
                extra={
                    "reason": exec_res.get("reason", "unknown"),
                    "details": exec_res.get("details", ""),
                    "phase": "post",
                },
            )
            return "error"  # Return error to trigger repair

        # Store the push result in shared store for success
        shared["push_result"] = {
            "success": exec_res.get("success", False),
            "branch": exec_res.get("branch", ""),
            "remote": exec_res.get("remote", ""),
        }

        if exec_res.get("success"):
            logger.info(
                "Push operation succeeded",
                extra={"branch": exec_res.get("branch"), "remote": exec_res.get("remote"), "phase": "post"},
            )

        return "default"
