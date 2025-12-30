"""Git log node implementation."""

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


class GitLogNode(Node):
    """
    Retrieve git commit history with filtering options.

    Interface:
    - Params: since: str  # Start date/tag/SHA (optional, e.g., "2024-01-01", "v1.0.0", "abc1234")
    - Params: until: str  # End date/tag/SHA (optional, default: HEAD)
    - Params: limit: int  # Maximum number of commits (optional, default: 20)
    - Params: author: str  # Filter by author email/name (optional)
    - Params: grep: str  # Filter commits by message content (optional)
    - Params: path: str  # Filter by file path (optional)
    - Params: working_directory: str  # Directory to run git commands (optional, default: current directory)
    - Writes: shared["commits"]: list[dict]  # List of commit objects
        - sha: str  # Full commit SHA
        - short_sha: str  # Short SHA (7 chars)
        - author_name: str  # Author name
        - author_email: str  # Author email
        - date: str  # ISO format date (2024-01-15T10:30:00)
        - timestamp: int  # Unix timestamp
        - subject: str  # First line of message
        - message: str  # Full commit message
        - body: str  # Rest of message (if multi-line)
    - Actions: default (always)

    Note:
        This node operates on the current working directory only.
        Use ISO dates for 'since' and 'until' parameters (e.g., "2024-01-01").
        Tags and branch names are also valid for since/until.
    """

    def __init__(self) -> None:
        """Initialize with retry support for transient git issues."""
        super().__init__(max_retries=2, wait=0.5)

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        """Extract parameters from node parameters."""
        # Get parameters from params
        since = self.params.get("since")
        until = self.params.get("until")
        limit = self.params.get("limit", 20)
        author = self.params.get("author")
        grep = self.params.get("grep")
        path = self.params.get("path")

        # Get working directory
        cwd = self.params.get("working_directory", ".")
        cwd = Path(cwd).expanduser().resolve()

        # Validate limit
        if not isinstance(limit, int) or limit < 1:
            raise ValueError(f"Invalid limit: {limit}. Must be positive integer.")

        logger.debug(
            "Preparing to get git log",
            extra={"working_directory": str(cwd), "limit": limit, "since": since, "until": until, "phase": "prep"},
        )

        return {
            "since": since,
            "until": until,
            "limit": limit,
            "author": author,
            "grep": grep,
            "path": path,
            "working_directory": str(cwd),
        }

    def _parse_commits(self, output: str) -> list[dict[str, Any]]:
        """Parse git log output into structured commit data.

        Args:
            output: Git log formatted output with | delimiters

        Returns:
            List of parsed commit dictionaries
        """
        commits: list[dict[str, Any]] = []

        if not output.strip():
            return commits

        # Split by our end marker
        raw_commits = output.strip().split("|ENDCOMMIT\n")

        for raw_commit in raw_commits:
            if not raw_commit.strip():
                continue

            # Split on first 7 delimiters to handle commit bodies with |
            parts = raw_commit.split("|", 7)

            if len(parts) >= 7:
                # Parse the commit body (may contain |)
                body = ""
                if len(parts) > 7:
                    # Remove the |ENDCOMMIT suffix if present
                    body = parts[7]
                    if body.endswith("|ENDCOMMIT"):
                        body = body[:-10]  # Remove last 10 chars ("|ENDCOMMIT")
                    body = body.strip()

                # Split subject and body
                subject = parts[6]
                full_message = subject
                if body:
                    full_message = f"{subject}\n\n{body}"

                commits.append({
                    "sha": parts[0],
                    "short_sha": parts[1],
                    "author_name": parts[2],
                    "author_email": parts[3],
                    "date": parts[4],  # ISO format
                    "timestamp": int(parts[5]),
                    "subject": subject,
                    "message": full_message,
                    "body": body,
                })

        return commits

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        """
        Execute git log command and parse the output.

        Returns:
            Dictionary with commits list

        Raises:
            subprocess.CalledProcessError: If git command fails
            subprocess.TimeoutExpired: If command takes too long
            ValueError: If not in a git repository
        """
        cwd = prep_res["working_directory"]

        logger.info("Getting git log", extra={"working_directory": cwd, "limit": prep_res["limit"], "phase": "exec"})

        # Build git log command with custom format
        # Format: SHA|short_sha|author_name|author_email|ISO_date|timestamp|subject|body|ENDCOMMIT
        cmd = ["git", "log", "--format=%H|%h|%an|%ae|%aI|%at|%s|%b|ENDCOMMIT", f"-n{prep_res['limit']}"]

        # Add optional filters
        if prep_res["since"]:
            cmd.append(f"--since={prep_res['since']}")
        if prep_res["until"]:
            cmd.append(f"--until={prep_res['until']}")
        if prep_res["author"]:
            cmd.extend(["--author", prep_res["author"]])
        if prep_res["grep"]:
            cmd.extend(["--grep", prep_res["grep"]])

        # Add path filter last (after --)
        if prep_res["path"]:
            cmd.extend(["--", prep_res["path"]])

        # Execute git log
        result = subprocess.run(  # noqa: S603
            cmd, cwd=cwd, capture_output=True, text=True, shell=False, timeout=30, check=False
        )

        # Check for errors
        if result.returncode != 0:
            if "not a git repository" in result.stderr.lower():
                raise ValueError(f"Directory '{cwd}' is not a git repository")
            elif "unknown revision" in result.stderr.lower():
                raise ValueError(f"Invalid revision reference in since/until parameters: {result.stderr}")
            elif "does not have any commits yet" in result.stderr.lower():
                # Empty repository - return empty list (not an error)
                logger.info("Repository has no commits yet")
                return {"commits": [], "status": "empty_repository"}
            else:
                raise subprocess.CalledProcessError(
                    result.returncode, result.args, output=result.stdout, stderr=result.stderr
                )

        # Parse the output
        commits = self._parse_commits(result.stdout)

        logger.info(
            "Git log retrieved successfully",
            extra={"working_directory": cwd, "commits_count": len(commits), "phase": "exec"},
        )

        return {"commits": commits, "status": "success"}

    def exec_fallback(self, prep_res: dict[str, Any], exc: Exception) -> dict[str, Any]:
        """Handle final failure after all retries with user-friendly messages."""
        cwd = prep_res["working_directory"]

        logger.error(
            f"Failed to get git log after {self.max_retries} retries",
            extra={"working_directory": cwd, "error": str(exc), "phase": "fallback"},
        )

        # Provide specific error messages
        error_msg = ""
        if isinstance(exc, ValueError) and "not a git repository" in str(exc):
            error_msg = f"Error: Directory '{cwd}' is not a git repository. Please run this command from within a git repository."
        elif isinstance(exc, ValueError) and "Invalid revision" in str(exc):
            error_msg = "Error: Invalid revision reference. Check that your since/until parameters are valid tags, branches, SHAs, or dates."
        elif isinstance(exc, subprocess.TimeoutExpired):
            error_msg = "Error: Git log command timed out after 30 seconds. Try reducing the limit or using more specific filters."
        elif isinstance(exc, subprocess.CalledProcessError):
            stderr_msg = exc.stderr if exc.stderr else "Unknown error"
            error_msg = f"Error: Git command failed with exit code {exc.returncode}. {stderr_msg}"
        elif isinstance(exc, FileNotFoundError):
            error_msg = "Error: Git is not installed or not available in PATH. Please install git and try again."
        else:
            error_msg = f"Error: Could not retrieve git log after {self.max_retries} retries. {exc!s}"

        # Return result dict with error
        return {"commits": [], "status": "error", "error": error_msg}

    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> Optional[str]:
        """Update shared store with commits and return action."""
        # Check for error status first
        if exec_res.get("status") == "error":
            shared["error"] = exec_res.get("error", "Git operation failed")
            shared["commits"] = []
            logger.error("Git log failed", extra={"error": exec_res.get("error", "Unknown error"), "phase": "post"})
            return "error"  # Return error to trigger repair

        # Store the commits in shared store for success
        shared["commits"] = exec_res.get("commits", [])

        if exec_res.get("status") == "empty_repository":
            logger.info("Repository has no commits", extra={"phase": "post"})

        return "default"
