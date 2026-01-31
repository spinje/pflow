"""Git commit node implementation."""

import logging
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

# Add pocketflow to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from pflow.pocketflow import Node

# Set up logging
logger = logging.getLogger(__name__)


class GitCommitNode(Node):
    """
    Create a git commit.

    Interface:
    - Params: message: str  # Commit message
    - Params: files: list[str]  # Files to add (optional, default: ["."])
    - Params: working_directory: str  # Directory to run git commands (optional, default: current directory)
    - Writes: shared["commit_sha"]: str  # Commit SHA
    - Writes: shared["commit_message"]: str  # Commit message (echoed)
    - Actions: default (always)

    Note:
        This node operates on the current working directory only.
        It cannot target remote repositories like GitHub nodes can.
    """

    def __init__(self) -> None:
        """Initialize with retry support for transient git issues."""
        super().__init__(max_retries=2, wait=0.5)

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        """Extract commit message and files from parameters."""
        # Get commit message from params
        message = self.params.get("message")
        if not message:
            raise ValueError("Commit message is required. Provide it as a parameter.")

        # Get files to add from params, default to ["."]
        files = self.params.get("files", ["."])

        # Ensure files is a list
        if isinstance(files, str):
            files = [files]

        # Get working directory from params, default to current directory
        cwd = self.params.get("working_directory", ".")
        cwd = Path(cwd).expanduser().resolve()

        logger.debug(
            "Preparing to create git commit",
            extra={
                "message": message[:50] + "..." if len(message) > 50 else message,
                "files_count": len(files),
                "working_directory": str(cwd),
                "phase": "prep",
            },
        )

        return {"message": message, "files": files, "working_directory": str(cwd)}

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        """
        Stage files and create a git commit.

        Returns:
            Dictionary with commit SHA and message

        Raises:
            subprocess.CalledProcessError: If git command fails
            subprocess.TimeoutExpired: If command takes too long
        """
        message = prep_res["message"]
        files = prep_res["files"]
        cwd = prep_res["working_directory"]

        logger.info(
            "Creating git commit",
            extra={
                "message": message[:50] + "..." if len(message) > 50 else message,
                "files_count": len(files),
                "working_directory": cwd,
                "phase": "exec",
            },
        )

        # TODO: Future enhancement - add working_directory parameter
        # cwd = prep_res.get("working_directory", None)

        # First, add files to staging area
        add_cmd = ["git", "add", *files]
        add_result = subprocess.run(  # noqa: S603
            add_cmd, cwd=cwd, capture_output=True, text=True, shell=False, timeout=30, check=False
        )

        if add_result.returncode != 0:
            if "not a git repository" in add_result.stderr.lower():
                raise ValueError(f"Directory '{cwd}' is not a git repository")
            else:
                raise subprocess.CalledProcessError(
                    add_result.returncode, add_result.args, output=add_result.stdout, stderr=add_result.stderr
                )

        logger.debug(f"Successfully staged {len(files)} file(s)")

        # Now create the commit
        commit_cmd = ["git", "commit", "-m", message]
        commit_result = subprocess.run(  # noqa: S603
            commit_cmd, cwd=cwd, capture_output=True, text=True, shell=False, timeout=30, check=False
        )

        # Handle "nothing to commit" case (exit code 1)
        if commit_result.returncode == 1 and "nothing to commit" in commit_result.stdout.lower():
            logger.info("Nothing to commit - working tree is clean")
            return {"commit_sha": "", "commit_message": message, "status": "nothing_to_commit"}

        # Handle other errors
        if commit_result.returncode != 0:
            raise subprocess.CalledProcessError(
                commit_result.returncode, commit_result.args, output=commit_result.stdout, stderr=commit_result.stderr
            )

        # Extract commit SHA from output
        # Look for pattern like "[main abc123] message" or "[branch abc123] message"
        sha_match = re.search(r"\[[\w/-]+ ([a-f0-9]+)\]", commit_result.stdout)
        commit_sha = sha_match.group(1) if sha_match else ""

        # If we couldn't find SHA in the output, try getting it with rev-parse
        if not commit_sha:
            rev_parse_result = subprocess.run(  # noqa: S603
                ["git", "rev-parse", "HEAD"],  # noqa: S607
                cwd=cwd,
                capture_output=True,
                text=True,
                shell=False,
                timeout=10,
                check=False,
            )
            if rev_parse_result.returncode == 0:
                commit_sha = rev_parse_result.stdout.strip()[:7]  # Get short SHA

        logger.info(
            "Git commit created successfully",
            extra={
                "commit_sha": commit_sha,
                "message": message[:50] + "..." if len(message) > 50 else message,
                "working_directory": cwd,
                "phase": "exec",
            },
        )

        return {"commit_sha": commit_sha, "commit_message": message, "status": "committed"}

    def exec_fallback(self, prep_res: dict[str, Any], exc: Exception) -> dict[str, Any]:
        """Handle final failure after all retries with user-friendly messages."""
        message = prep_res["message"]
        cwd = prep_res["working_directory"]

        logger.error(
            f"Failed to create git commit after {self.max_retries} retries",
            extra={"working_directory": cwd, "error": str(exc), "phase": "fallback"},
        )

        # Provide specific error messages based on exception type
        error_msg = ""
        if isinstance(exc, ValueError) and "not a git repository" in str(exc):
            error_msg = f"Error: Directory '{cwd}' is not a git repository. Please run this command from within a git repository."
        elif isinstance(exc, subprocess.TimeoutExpired):
            error_msg = "Error: Git command timed out after 30 seconds. The repository may be very large or there may be system issues."
        elif isinstance(exc, subprocess.CalledProcessError):
            stderr_msg = exc.stderr if exc.stderr else "Unknown error"
            error_msg = f"Error: Git command failed with exit code {exc.returncode}. {stderr_msg}"
        elif isinstance(exc, FileNotFoundError):
            error_msg = "Error: Git is not installed or not available in PATH. Please install git and try again."
        else:
            error_msg = f"Error: Could not create commit after {self.max_retries} retries. {exc!s}"

        # Return a result dict with the error message
        return {"commit_sha": "", "commit_message": message, "status": "error", "error": error_msg}

    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> Optional[str]:
        """Update shared store with commit results and return action."""
        # Check for error status first
        if exec_res.get("status") == "error":
            shared["error"] = exec_res.get("error", "Git operation failed")
            shared["commit_sha"] = ""
            shared["commit_message"] = exec_res.get("commit_message", "")
            shared["commit_status"] = "error"
            logger.error("Git commit failed", extra={"error": exec_res.get("error", "Unknown error"), "phase": "post"})
            return "error"  # Return error to trigger repair

        # Store the commit SHA and message in shared store for success
        shared["commit_sha"] = exec_res.get("commit_sha", "")
        shared["commit_message"] = exec_res.get("commit_message", "")

        if exec_res.get("status") == "nothing_to_commit":
            logger.info("No changes to commit", extra={"phase": "post"})
            shared["commit_status"] = "nothing_to_commit"

        return "default"
