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
    - Params: since: str  # (optional) Start point: tag or date e.g. "v1.0.0" or "2024-01-01"
    - Params: until: str  # (optional) End point: tag or date. Default: HEAD
    - Params: limit: int  # (optional) Maximum commits to return. Default: 20
    - Params: author: str  # (optional) Filter by author email/name
    - Params: grep: str  # (optional) Filter commits by message content
    - Params: path: str  # (optional) Filter by file path
    - Params: working_directory: str  # (optional) Directory for git commands. Default: current directory
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
        Auto-detects whether since/until are git refs or dates:
        - Git refs (tags, branches, SHAs): Uses commit range syntax (e.g., "v1.0.0..HEAD")
        - Dates: Uses --since/--until flags (e.g., "--since=2024-01-01")

        Examples:
        - since="v1.0.0" → commits after tag v1.0.0 up to HEAD
        - since="v1.0.0", until="v2.0.0" → commits between the two tags
        - since="2024-01-01" → commits since that date
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

    def _is_git_ref(self, ref: str, cwd: str) -> bool:
        """Check if a string is a valid git ref (tag, branch, SHA).

        Args:
            ref: The reference to check
            cwd: Working directory for git command

        Returns:
            True if ref is a valid git reference, False if it's likely a date
        """
        # Try to resolve the ref using git rev-parse
        result = subprocess.run(  # noqa: S603
            ["git", "rev-parse", "--verify", "--quiet", ref],  # noqa: S607
            cwd=cwd,
            capture_output=True,
            text=True,
            shell=False,
            timeout=10,
            check=False,
        )
        return result.returncode == 0

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:  # noqa: C901
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

        # Handle since/until - detect if they're git refs or dates
        since = prep_res["since"]
        until = prep_res["until"]

        # Check if since is a git ref (tag, branch, SHA) or a date
        if since:
            if self._is_git_ref(since, cwd):
                # Use commit range syntax for refs
                end_ref = until if until and self._is_git_ref(until, cwd) else "HEAD"
                cmd.append(f"{since}..{end_ref}")
                # Clear until since we've handled it in the range
                until = None if (until and self._is_git_ref(until, cwd)) else until
            else:
                # Treat as date
                cmd.append(f"--since={since}")

        if until:
            if self._is_git_ref(until, cwd):
                # If we get here, since wasn't a ref but until is
                cmd.append(until)
            else:
                cmd.append(f"--until={until}")
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
