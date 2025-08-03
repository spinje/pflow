"""GitHub issues listing node implementation."""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

# Add pocketflow to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from pocketflow import Node


class ListIssuesNode(Node):
    """
    List GitHub repository issues.

    Interface:
    - Reads: shared["repo"]: str  # Repository in owner/repo format (optional, default: current repo)
    - Reads: shared["state"]: str  # Issue state: open, closed, all (optional, default: open)
    - Reads: shared["limit"]: int  # Maximum issues to return (optional, default: 30)
    - Writes: shared["issues"]: list[dict]  # Array of issue objects
        - number: int  # Issue number
        - title: str  # Issue title
        - state: str  # Issue state (OPEN, CLOSED)
        - author: dict  # Issue author information
            - login: str  # Username
        - labels: list[dict]  # Issue labels
            - name: str  # Label name
        - createdAt: str  # Creation timestamp
        - updatedAt: str  # Last update timestamp
    - Actions: default (always)
    """

    name = "github-list-issues"  # CRITICAL: Required for registry discovery

    def __init__(self, max_retries: int = 3, wait: float = 1.0):
        """Initialize the GitHub list issues node with retry support."""
        super().__init__(max_retries=max_retries, wait=wait)

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        """Extract and validate inputs from shared store with parameter fallback."""
        # Check authentication first
        auth_result = subprocess.run(  # noqa: S603
            ["gh", "auth", "status"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=10,
        )

        if auth_result.returncode != 0:
            raise ValueError("GitHub CLI not authenticated. Please run 'gh auth login' to authenticate with GitHub.")

        # Extract repo with fallback: shared → params → None (gh CLI uses current repo)
        repo = shared.get("repo") or self.params.get("repo")

        # Extract state with fallback: shared → params → default
        state = shared.get("state") or self.params.get("state", "open")
        # Validate state
        valid_states = ["open", "closed", "all"]
        if state not in valid_states:
            raise ValueError(f"Invalid issue state '{state}'. Must be one of: {', '.join(valid_states)}")

        # Extract limit with fallback: shared → params → default
        limit = shared.get("limit") or self.params.get("limit", 30)
        # Validate and clamp limit to valid range
        try:
            limit = int(limit)
        except (TypeError, ValueError) as e:
            raise ValueError(f"Invalid limit value '{limit}'. Must be an integer between 1 and 100.") from e

        # Clamp to valid range
        if limit < 1:
            limit = 1
        elif limit > 100:
            limit = 100

        return {"repo": repo, "state": state, "limit": limit}

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        """Execute GitHub CLI call - NO try/except blocks! Let exceptions bubble up."""
        # Build command
        cmd = ["gh", "issue", "list", "--json", "number,title,state,author,labels,createdAt,updatedAt"]

        # Add repo if specified
        if prep_res["repo"]:
            cmd.extend(["--repo", prep_res["repo"]])

        # Add state and limit
        cmd.extend(["--state", prep_res["state"]])
        cmd.extend(["--limit", str(prep_res["limit"])])

        # Execute command - NO try/except! Let exceptions bubble for retry
        result = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            shell=False,  # CRITICAL: Security requirement
            timeout=30,  # Prevent hanging
        )

        # Check return code
        if result.returncode != 0:
            # Let the error bubble up for retry mechanism
            raise subprocess.CalledProcessError(result.returncode, cmd, output=result.stdout, stderr=result.stderr)

        # Parse JSON response
        issues = json.loads(result.stdout) if result.stdout else []

        return {"issues": issues}

    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
        """Store results in shared store."""
        # Store the complete issues list with native field names
        shared["issues"] = exec_res["issues"]

        return "default"  # Always return "default"

    def exec_fallback(self, prep_res: dict[str, Any], exc: Exception) -> None:
        """Handle errors after all retries exhausted - transform to user messages."""
        error_msg = str(exc)

        # Transform technical errors to actionable user guidance
        if "gh: command not found" in error_msg:
            raise ValueError(
                "GitHub CLI (gh) is not installed. "
                "Install it with: brew install gh (macOS) or see https://cli.github.com/manual/installation"
            )
        elif "repository not found" in error_msg.lower() or "not found" in error_msg.lower():
            repo = prep_res.get("repo", "current repository")
            raise ValueError(
                f"Repository '{repo}' not found or you don't have access. "
                f"Please verify the repository name (format: owner/repo) and your permissions."
            )
        elif "authentication required" in error_msg.lower() or "unauthorized" in error_msg.lower():
            raise ValueError("GitHub authentication failed. Please run 'gh auth login' to authenticate with GitHub.")
        elif "rate limit" in error_msg.lower():
            raise ValueError(
                "GitHub API rate limit exceeded. "
                "Please wait a few minutes and try again, or authenticate with 'gh auth login' for higher limits."
            )
        else:
            # Generic error with context
            raise ValueError(
                f"Failed to list issues after {self.max_retries} attempts. "
                f"Repository: {prep_res.get('repo', 'current')}, "
                f"State: {prep_res.get('state', 'unknown')}, "
                f"Limit: {prep_res.get('limit', 'unknown')}, "
                f"Error: {exc}"
            )
