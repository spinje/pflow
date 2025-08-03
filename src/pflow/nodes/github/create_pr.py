"""GitHub pull request creation node implementation."""

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

# Add pocketflow to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from pocketflow import Node


class GitHubCreatePRNode(Node):
    """
    Create a GitHub pull request.

    Interface:
    - Reads: shared["title"]: str  # PR title
    - Reads: shared["body"]: str  # PR description (optional, default: empty)
    - Reads: shared["head"]: str  # Head branch name
    - Reads: shared["base"]: str  # Base branch name (optional, default: main)
    - Reads: shared["repo"]: str  # Repository (optional, default: current repo)
    - Writes: shared["pr_data"]: dict  # Pull request details
        - number: int  # PR number
        - url: str  # PR URL
        - title: str  # PR title
        - state: str  # PR state (OPEN)
        - author: dict  # PR author
            - login: str  # Username
    - Actions: default (always)
    """

    name = "github-create-pr"  # CRITICAL: Required for registry discovery

    def __init__(self, max_retries: int = 3, wait: float = 1.0):
        """Initialize the GitHub PR creation node with retry support."""
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

        # Extract required fields with fallback: shared → params → error
        title = shared.get("title") or self.params.get("title")
        if not title:
            raise ValueError(
                "GitHub PR creation requires 'title' in shared store or parameters. "
                "Please ensure previous nodes set shared['title'] "
                "or provide --title parameter."
            )

        body = shared.get("body") or self.params.get("body", "")

        head = shared.get("head") or self.params.get("head")
        if not head:
            raise ValueError(
                "GitHub PR creation requires 'head' branch in shared store or parameters. "
                "Please ensure previous nodes set shared['head'] "
                "or provide --head parameter."
            )

        # Extract optional fields with defaults
        base = shared.get("base") or self.params.get("base", "main")
        repo = shared.get("repo") or self.params.get("repo")

        return {"title": str(title), "body": str(body), "head": str(head), "base": str(base), "repo": repo}

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        """Execute GitHub CLI to create PR - NO try/except blocks! Let exceptions bubble up."""
        # Step 1: Create PR (returns URL only, not JSON)
        cmd = [
            "gh",
            "pr",
            "create",
            "--title",
            prep_res["title"],
            "--body",
            prep_res["body"],
            "--base",
            prep_res["base"],
            "--head",
            prep_res["head"],
        ]

        # Add repo if specified
        if prep_res["repo"]:
            cmd.extend(["--repo", prep_res["repo"]])

        # Execute create command - NO try/except! Let exceptions bubble for retry
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

        # Step 2: Parse URL from stdout (gh pr create returns URL, not JSON)
        pr_url = result.stdout.strip()
        if not pr_url:
            raise ValueError("GitHub CLI returned empty response when creating PR")

        # Step 3: Extract PR number from URL using regex
        # Example URL: https://github.com/owner/repo/pull/456
        match = re.search(r"/pull/(\d+)", pr_url)
        if not match:
            raise ValueError(f"Could not parse PR number from URL: {pr_url}")

        pr_number = match.group(1)

        # Step 4: Get full PR data using gh pr view
        cmd = ["gh", "pr", "view", pr_number, "--json", "number,url,title,state,author"]

        if prep_res["repo"]:
            cmd.extend(["--repo", prep_res["repo"]])

        # Execute view command to get full PR data
        result = subprocess.run(  # noqa: S603
            cmd, capture_output=True, text=True, shell=False, timeout=30
        )

        # Check return code
        if result.returncode != 0:
            # Let the error bubble up for retry mechanism
            raise subprocess.CalledProcessError(result.returncode, cmd, output=result.stdout, stderr=result.stderr)

        # Parse JSON response
        pr_data = json.loads(result.stdout)

        # Ensure we have the full URL (sometimes gh pr view returns a different format)
        pr_data["url"] = pr_url

        # Ensure number is an integer
        pr_data["number"] = int(pr_data.get("number", pr_number))

        return {"pr_data": pr_data}

    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
        """Store results in shared store."""
        # Store the complete PR data
        shared["pr_data"] = exec_res["pr_data"]

        return "default"  # Always return "default"

    def exec_fallback(self, prep_res: dict[str, Any], exc: Exception) -> None:
        """Handle errors after all retries exhausted - transform to user messages."""
        error_msg = str(exc)

        # Transform technical errors to actionable user guidance
        # Check more specific errors first, then general ones
        if "gh: command not found" in error_msg:
            raise ValueError(
                "GitHub CLI (gh) is not installed. "
                "Install it with: brew install gh (macOS) or see https://cli.github.com/manual/installation"
            )
        elif "authentication required" in error_msg.lower() or "unauthorized" in error_msg.lower():
            raise ValueError("GitHub authentication failed. Please run 'gh auth login' to authenticate with GitHub.")
        elif "rate limit" in error_msg.lower():
            raise ValueError(
                "GitHub API rate limit exceeded. "
                "Please wait a few minutes and try again, or authenticate with 'gh auth login' for higher limits."
            )
        elif "already exists" in error_msg.lower():
            raise ValueError(
                f"A pull request already exists for branch '{prep_res['head']}'. "
                f"Please check existing PRs or use a different branch."
            )
        elif "no commits between" in error_msg.lower():
            raise ValueError(
                f"No changes to create PR: branches '{prep_res['base']}' and '{prep_res['head']}' are identical. "
                f"Please make commits on '{prep_res['head']}' before creating a PR."
            )
        elif "branch" in error_msg.lower() and "not found" in error_msg.lower():
            # Check for branch-specific errors before generic "not found"
            raise ValueError(
                f"Branch not found. Please verify that both '{prep_res['base']}' and '{prep_res['head']}' branches exist."
            )
        elif "repository not found" in error_msg.lower() or "not found" in error_msg.lower():
            # Generic "not found" error - likely repository issue
            repo = prep_res.get("repo", "current repository")
            raise ValueError(
                f"Repository '{repo}' not found or you don't have access. "
                f"Please verify the repository name (format: owner/repo) and your permissions."
            )
        else:
            # Generic error with context
            raise ValueError(
                f"Failed to create PR after {self.max_retries} attempts. "
                f"Title: {prep_res.get('title', 'unknown')}, "
                f"Head: {prep_res.get('head', 'unknown')}, "
                f"Base: {prep_res.get('base', 'unknown')}, "
                f"Repository: {prep_res.get('repo', 'current')}, "
                f"Error: {exc}"
            )
