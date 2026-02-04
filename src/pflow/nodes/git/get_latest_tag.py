"""Git get latest tag node implementation."""

import logging
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

# Add pocketflow to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from pflow.pocketflow import Node

# Set up logging
logger = logging.getLogger(__name__)


class GitGetLatestTagNode(Node):
    """
    Get the latest git tag from the repository.

    Interface:
    - Params: pattern: str  # Tag pattern filter (optional, e.g., "v*", "release-*")
    - Params: working_directory: str  # Directory to run git commands (optional, default: current directory)
    - Writes: shared["latest_tag"]: dict  # Latest tag information
        - name: str  # Tag name (e.g., "v1.2.3")
        - sha: str  # Commit SHA the tag points to
        - date: str  # Tag/commit date (ISO format)
        - message: str  # Tag message (empty for lightweight tags)
        - is_annotated: bool  # Whether tag is annotated
    - Actions: default (always)

    Note:
        Returns empty dict if no tags exist or no tags match the pattern.
        This is not an error condition - workflows should handle empty results.
        Tags are sorted by version number (semantic versioning aware).
    """

    def __init__(self) -> None:
        """Initialize with retry support for transient git issues."""
        super().__init__(max_retries=2, wait=0.5)

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        """Extract parameters from node parameters."""
        # Get pattern filter (optional)
        pattern = self.params.get("pattern")

        # Get working directory
        cwd = self.params.get("working_directory", ".")
        cwd = Path(cwd).expanduser().resolve()

        logger.debug(
            "Preparing to get latest git tag",
            extra={"working_directory": str(cwd), "pattern": pattern, "phase": "prep"},
        )

        return {"pattern": pattern, "working_directory": str(cwd)}

    def _parse_tag_output(self, output: str) -> dict[str, Any]:
        """Parse git for-each-ref output into tag data.

        Args:
            output: Git command output with format: name|sha|date|subject|body

        Returns:
            Dictionary with tag information or empty dict if no output
        """
        if not output.strip():
            return {}

        # Split on first 4 pipes to handle messages with pipes
        parts = output.strip().split("|", 4)

        if len(parts) < 4:
            # Malformed output, return empty
            logger.warning(f"Malformed git output: {output}")
            return {}

        tag_name = parts[0]
        sha = parts[1]
        date = parts[2]
        subject = parts[3] if len(parts) > 3 else ""

        # Check if it's an annotated tag by looking for tag object
        # Annotated tags have a subject, lightweight tags don't
        is_annotated = bool(subject)

        # For lightweight tags, we need to get the commit message
        # For annotated tags, use the tag message
        message = "" if not is_annotated and sha else subject

        return {"name": tag_name, "sha": sha, "date": date, "message": message, "is_annotated": is_annotated}

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        """
        Execute git command to get the latest tag.

        Returns:
            Dictionary with latest_tag information

        Raises:
            subprocess.CalledProcessError: If git command fails
            subprocess.TimeoutExpired: If command takes too long
            ValueError: If not in a git repository
        """
        cwd = prep_res["working_directory"]
        pattern = prep_res["pattern"]

        logger.info("Getting latest git tag", extra={"working_directory": cwd, "pattern": pattern, "phase": "exec"})

        # Build git command using for-each-ref for better control
        # Format: refname|objectname|creatordate|subject
        cmd = [
            "git",
            "for-each-ref",
            "--sort=-version:refname",  # Sort by version (semantic versioning aware)
            "--count=1",  # Only get the latest
            "--format=%(refname:short)|%(objectname)|%(creatordate:iso)|%(contents:subject)",
        ]

        # Add pattern filter if specified
        if pattern:
            # Validate pattern doesn't contain dangerous characters
            if ";" in pattern or "&" in pattern or "|" in pattern:
                raise ValueError(f"Invalid pattern: {pattern}. Pattern cannot contain shell operators.")
            cmd.append(f"refs/tags/{pattern}")
        else:
            cmd.append("refs/tags")

        # Execute git command
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, shell=False, timeout=30, check=False)

        # Check for errors
        if result.returncode != 0:
            if "not a git repository" in result.stderr.lower():
                raise ValueError(f"Directory '{cwd}' is not a git repository")
            elif "fatal:" in result.stderr.lower():
                # Other fatal git errors
                raise subprocess.CalledProcessError(
                    result.returncode, result.args, output=result.stdout, stderr=result.stderr
                )
            # No tags found is not an error - return empty
            # git for-each-ref returns 0 even with no results

        # Parse the output
        latest_tag = self._parse_tag_output(result.stdout)

        if latest_tag:
            logger.info(
                "Found latest tag", extra={"tag_name": latest_tag["name"], "working_directory": cwd, "phase": "exec"}
            )
        else:
            logger.info("No tags found", extra={"pattern": pattern, "working_directory": cwd, "phase": "exec"})

        return {"latest_tag": latest_tag, "status": "success"}

    def exec_fallback(self, prep_res: dict[str, Any], exc: Exception) -> dict[str, Any]:
        """Handle final failure after all retries with user-friendly messages."""
        cwd = prep_res["working_directory"]
        pattern = prep_res["pattern"]

        logger.error(
            f"Failed to get latest tag after {self.max_retries} retries",
            extra={"working_directory": cwd, "pattern": pattern, "error": str(exc), "phase": "fallback"},
        )

        # Provide specific error messages
        error_msg = ""
        if isinstance(exc, ValueError) and "not a git repository" in str(exc):
            error_msg = f"Error: Directory '{cwd}' is not a git repository. Please run this command from within a git repository."
        elif isinstance(exc, ValueError) and "Invalid pattern" in str(exc):
            error_msg = f"Error: Invalid tag pattern '{pattern}'. Pattern cannot contain shell operators."
        elif isinstance(exc, subprocess.TimeoutExpired):
            error_msg = "Error: Git command timed out after 30 seconds. The repository may be very large or there may be system issues."
        elif isinstance(exc, subprocess.CalledProcessError):
            stderr_msg = exc.stderr if exc.stderr else "Unknown error"
            error_msg = f"Error: Git command failed with exit code {exc.returncode}. {stderr_msg}"
        elif isinstance(exc, FileNotFoundError):
            error_msg = "Error: Git is not installed or not available in PATH. Please install git and try again."
        else:
            error_msg = f"Error: Could not get latest tag after {self.max_retries} retries. {exc!s}"

        # Return result dict with error
        return {"latest_tag": {}, "status": "error", "error": error_msg}

    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> Optional[str]:
        """Update shared store with latest tag and return action."""
        # Check for error status first
        if exec_res.get("status") == "error":
            shared["error"] = exec_res.get("error", "Git operation failed")
            shared["latest_tag"] = {}
            logger.error(
                "Failed to get latest tag", extra={"error": exec_res.get("error", "Unknown error"), "phase": "post"}
            )
            return "error"  # Return error to trigger repair

        # Store the latest tag in shared store for success
        shared["latest_tag"] = exec_res.get("latest_tag", {})

        if not exec_res.get("latest_tag"):
            logger.info("No tags found in repository", extra={"phase": "post"})

        return "default"
