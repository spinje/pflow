"""GitHub issue retrieval node implementation."""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

# Add pocketflow to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from pflow.pocketflow import Node


class GetIssueNode(Node):
    """
    Get GitHub issue details.

    Interface:
    - Params: issue_number: str  # Issue number to fetch
    - Params: repo: str  # Repository in owner/repo format (optional, default: current repo)
    - Writes: shared["issue_data"]: dict  # Complete issue details
        - number: int  # Issue number
        - title: str  # Issue title
        - body: str  # Issue description
        - state: str  # Issue state (OPEN, CLOSED)
        - author: dict  # Issue author information
            - login: str  # Username
            - name: str  # Full name
            - id: str  # User ID
        - labels: list[dict]  # Issue labels
            - name: str  # Label name
            - color: str  # Label color
            - description: str  # Label description
        - assignees: list[dict]  # Issue assignees
            - login: str  # Username
            - name: str  # Full name
        - createdAt: str  # Creation timestamp
        - updatedAt: str  # Last update timestamp
    - Actions: default (always)
    """

    name = "github-get-issue"  # CRITICAL: Required for registry discovery

    def __init__(self, max_retries: int = 3, wait: float = 1.0):
        """Initialize the GitHub issue node with retry support."""
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

        # Extract issue number from params
        issue_number = self.params.get("issue_number")
        if not issue_number:
            raise ValueError(
                "GitHub issue node requires 'issue_number' in shared store or parameters. "
                "Please ensure previous nodes set shared['issue_number'] "
                "or provide --issue-number parameter."
            )

        # Extract repo from params (gh CLI uses current repo if None)
        repo = self.params.get("repo")

        return {
            "issue_number": str(issue_number),  # Ensure string for CLI
            "repo": repo,
        }

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        """Execute GitHub CLI call - NO try/except blocks! Let exceptions bubble up."""
        # Build command
        cmd = [
            "gh",
            "issue",
            "view",
            prep_res["issue_number"],
            "--json",
            "number,title,body,state,author,labels,createdAt,updatedAt,assignees",
        ]

        # Add repo if specified
        if prep_res["repo"]:
            cmd.extend(["--repo", prep_res["repo"]])

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
        issue_data = json.loads(result.stdout)

        return {"issue_data": issue_data}

    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
        """Store results in shared store."""
        # Store the complete issue data with native field names
        shared["issue_data"] = exec_res["issue_data"]

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
        elif "could not resolve to an Issue" in error_msg:
            issue_num = prep_res.get("issue_number", "unknown")
            repo_msg = f" in repository {prep_res['repo']}" if prep_res.get("repo") else ""
            raise ValueError(f"Issue #{issue_num} not found{repo_msg}. Please verify the issue number and repository.")
        elif "authentication required" in error_msg.lower() or "unauthorized" in error_msg.lower():
            raise ValueError("GitHub authentication failed. Please run 'gh auth login' to authenticate with GitHub.")
        elif "repository not found" in error_msg.lower() or "not found" in error_msg.lower():
            repo = prep_res.get("repo", "current repository")
            raise ValueError(
                f"Repository '{repo}' not found or you don't have access. "
                f"Please verify the repository name (format: owner/repo) and your permissions."
            )
        elif "rate limit" in error_msg.lower():
            raise ValueError(
                "GitHub API rate limit exceeded. "
                "Please wait a few minutes and try again, or authenticate with 'gh auth login' for higher limits."
            )
        else:
            # Generic error with context
            raise ValueError(
                f"Failed to fetch issue after {self.max_retries} attempts. "
                f"Issue: {prep_res.get('issue_number', 'unknown')}, "
                f"Repository: {prep_res.get('repo', 'current')}, "
                f"Error: {exc}"
            )
