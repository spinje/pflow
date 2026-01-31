"""GitHub issues listing node implementation."""

import json
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# Add pocketflow to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from pflow.pocketflow import Node


class ListIssuesNode(Node):
    """
    List GitHub repository issues.

    Interface:
    - Params: repo: str  # Repository in owner/repo format (optional, default: current repo)
    - Params: state: str  # Issue state: open, closed, all (optional, default: open)
    - Params: limit: int  # Maximum issues to return (optional, default: 30)
    - Params: since: str  # Filter issues created after this date (optional)
        # Accepts: ISO date (2025-08-20), relative (7 days ago), or YYYY-MM-DD
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

    def _parse_relative_date(self, date_str: str) -> str:
        """Parse relative date strings like '7 days ago' into YYYY-MM-DD format.

        Args:
            date_str: Relative date string (e.g., "7 days ago", "yesterday", "1 week ago")

        Returns:
            Date in YYYY-MM-DD format
        """
        date_str_lower = date_str.lower().strip()
        today = datetime.now()

        if date_str_lower == "yesterday":
            target_date = today - timedelta(days=1)
            return target_date.strftime("%Y-%m-%d")

        if date_str_lower == "today":
            return today.strftime("%Y-%m-%d")

        # Parse patterns like "7 days ago", "1 week ago", "2 months ago"
        match = re.match(r"^(\d+)\s+(day|days|week|weeks|month|months)\s+ago$", date_str_lower)
        if match:
            amount = int(match.group(1))
            unit = match.group(2)

            if unit in ["day", "days"]:
                target_date = today - timedelta(days=amount)
            elif unit in ["week", "weeks"]:
                target_date = today - timedelta(weeks=amount)
            elif unit in ["month", "months"]:
                # Approximate: 30 days per month
                target_date = today - timedelta(days=amount * 30)
            else:
                raise ValueError(f"Unsupported time unit: {unit}")

            return target_date.strftime("%Y-%m-%d")

        raise ValueError(f"Cannot parse relative date: {date_str}")

    def _normalize_date(self, date_str: str | None) -> str | None:
        """Convert various date formats to GitHub search format (YYYY-MM-DD).

        Supports:
        - ISO dates: 2025-08-20, 2025-08-20T10:30:00
        - Relative: "7 days ago", "1 week ago", "yesterday"
        - Date only: 2025-08-20

        Returns:
            String in YYYY-MM-DD format for GitHub search
        """
        if not date_str:
            return None

        date_str = date_str.strip()

        # Check again after stripping - empty string case
        if not date_str:
            return None

        # Already in YYYY-MM-DD format
        if re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
            return date_str

        # ISO datetime - extract date part
        if re.match(r"^\d{4}-\d{2}-\d{2}T", date_str):
            return date_str[:10]

        # Relative dates
        if "ago" in date_str.lower() or date_str.lower() in ["yesterday", "today"]:
            try:
                return self._parse_relative_date(date_str)
            except ValueError:
                # If we can't parse it, let GitHub handle it (will likely fail)
                return date_str

        # Try parsing as various formats
        for fmt in ["%Y/%m/%d", "%m/%d/%Y", "%d-%m-%Y"]:
            try:
                dt = datetime.strptime(date_str, fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue

        # If we can't parse it, pass it through and let GitHub handle the error
        return date_str

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

        # Extract repo from params (gh CLI uses current repo if None)
        repo = self.params.get("repo")

        # Extract state from params with default
        state = self.params.get("state", "open")
        # Validate state
        valid_states = ["open", "closed", "all"]
        if state not in valid_states:
            raise ValueError(f"Invalid issue state '{state}'. Must be one of: {', '.join(valid_states)}")

        # Extract limit from params with default
        limit = self.params.get("limit", 30)
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

        # Extract since from params
        since = self.params.get("since")

        # Normalize date if provided
        normalized_since = None
        if since:
            normalized_since = self._normalize_date(since)

        return {"repo": repo, "state": state, "limit": limit, "since": normalized_since}

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        """Execute GitHub CLI call - NO try/except blocks! Let exceptions bubble up."""
        # Build command
        cmd = ["gh", "issue", "list", "--json", "number,title,state,author,labels,createdAt,updatedAt"]

        # Add repo if specified
        if prep_res["repo"]:
            cmd.extend(["--repo", prep_res["repo"]])

        # Handle date filtering via search query
        if prep_res.get("since"):
            # Build search query combining date and state
            search_parts = []

            # Add date filter
            search_parts.append(f"created:>{prep_res['since']}")

            # Add state filter if not "all"
            if prep_res["state"] != "all":
                search_parts.append(f"is:{prep_res['state']}")

            search_query = " ".join(search_parts)
            cmd.extend(["--search", search_query])
        else:
            # Use traditional state flag when no date filter
            cmd.extend(["--state", prep_res["state"]])

        # Add limit
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
        elif "Invalid query" in error_msg and prep_res.get("since"):
            raise ValueError(
                f"Invalid date format '{prep_res['since']}'. "
                f"Use ISO date (2025-08-20), relative date (7 days ago), or YYYY-MM-DD format."
            )
        elif "could not parse" in error_msg.lower() and prep_res.get("since"):
            raise ValueError(
                f"GitHub couldn't parse the date '{prep_res['since']}'. Try using YYYY-MM-DD format (e.g., 2025-08-20)."
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
