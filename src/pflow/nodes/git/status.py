"""Git status node implementation."""

import logging
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

# Add pocketflow to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from pocketflow import Node

# Set up logging
logger = logging.getLogger(__name__)


class GitStatusNode(Node):
    """
    Get git repository status.

    Interface:
    - Reads: shared["working_directory"]: str  # Directory to check status (optional, default: current directory)
    - Writes: shared["git_status"]: dict  # Repository status information
        - modified: list[str]  # Modified files
        - untracked: list[str]  # Untracked files
        - staged: list[str]  # Staged files
        - branch: str  # Current branch name
        - ahead: int  # Commits ahead of remote
        - behind: int  # Commits behind remote
    - Actions: default (always)

    Note:
        This node operates on the current working directory only.
        It cannot target remote repositories like GitHub nodes can.
    """

    def __init__(self) -> None:
        """Initialize with retry support for transient git issues."""
        super().__init__(max_retries=2, wait=0.5)

    def prep(self, shared: dict[str, Any]) -> str:
        """Extract working directory from shared store or use current directory."""
        # Get working directory from shared or params, default to current directory
        cwd = shared.get("working_directory") or self.params.get("working_directory", ".")

        # Normalize the path
        cwd = Path(cwd).expanduser().resolve()

        logger.debug("Preparing to get git status", extra={"working_directory": str(cwd), "phase": "prep"})
        return str(cwd)

    def _parse_porcelain_output(self, output: str) -> dict[str, Any]:  # noqa: C901
        """Parse git porcelain v2 output into structured data.

        Args:
            output: Git porcelain v2 formatted output

        Returns:
            Dictionary with parsed git status data
        """
        lines = output.strip().split("\n") if output.strip() else []

        status_data: dict[str, Any] = {
            "modified": [],
            "untracked": [],
            "staged": [],
            "branch": "main",  # Default branch name
            "ahead": 0,
            "behind": 0,
        }

        # Type-safe references to the lists
        modified_files: list[str] = status_data["modified"]
        untracked_files: list[str] = status_data["untracked"]
        staged_files: list[str] = status_data["staged"]

        for line in lines:
            if not line:
                continue

            # Parse branch information
            if line.startswith("# branch.head"):
                # Format: # branch.head <branch_name>
                parts = line.split()
                if len(parts) >= 3:
                    status_data["branch"] = parts[2]

            elif line.startswith("# branch.ab"):
                # Format: # branch.ab +<ahead> -<behind>
                match = re.match(r"# branch\.ab \+(\d+) -(\d+)", line)
                if match:
                    status_data["ahead"] = int(match.group(1))
                    status_data["behind"] = int(match.group(2))

            # Parse tracked file changes
            elif line.startswith("1") or line.startswith("2"):
                # Format: 1 XY sub mH mI mW hH hI path
                # Where X = staged status, Y = working tree status
                parts = line.split()
                if len(parts) >= 9:
                    staged_status = parts[1][0]
                    working_status = parts[1][1]
                    file_path = parts[8]  # The path is at index 8

                    # Check staged status
                    if staged_status in ["M", "A", "D", "R", "C"] and file_path not in staged_files:
                        staged_files.append(file_path)

                    # Check working tree status
                    if working_status == "M" and file_path not in modified_files:
                        modified_files.append(file_path)

            # Parse untracked files
            elif line.startswith("?"):
                # Format: ? path
                parts = line.split(maxsplit=1)
                if len(parts) >= 2:
                    file_path = parts[1]
                    if file_path not in untracked_files:
                        untracked_files.append(file_path)

        # Sort the file lists for consistent output
        modified_files.sort()
        untracked_files.sort()
        staged_files.sort()

        return status_data

    def exec(self, prep_res: str) -> dict[str, Any]:
        """
        Execute git status command and parse the output.

        Returns:
            Structured git status information

        Raises:
            subprocess.CalledProcessError: If git command fails
            subprocess.TimeoutExpired: If command takes too long
        """
        cwd = prep_res

        logger.info("Getting git status", extra={"working_directory": cwd, "phase": "exec"})

        # TODO: Future enhancement - add working_directory parameter
        # cwd = prep_res.get("working_directory", None)

        # Execute git status with porcelain v2 format for machine-readable output
        result = subprocess.run(  # noqa: S603
            ["git", "status", "--porcelain=v2", "--branch"],  # noqa: S607
            cwd=cwd,
            capture_output=True,
            text=True,
            shell=False,
            timeout=30,
            check=False,  # We'll handle errors ourselves
        )

        # Check for "not a git repository" error
        if result.returncode != 0:
            if "not a git repository" in result.stderr.lower():
                raise ValueError(f"Directory '{cwd}' is not a git repository")
            else:
                # Re-raise as CalledProcessError for other git errors
                raise subprocess.CalledProcessError(
                    result.returncode, result.args, output=result.stdout, stderr=result.stderr
                )

        # Parse the porcelain v2 output using helper method
        status_data = self._parse_porcelain_output(result.stdout)

        logger.info(
            "Git status retrieved successfully",
            extra={
                "working_directory": cwd,
                "branch": status_data["branch"],
                "modified_count": len(status_data["modified"]),
                "untracked_count": len(status_data["untracked"]),
                "staged_count": len(status_data["staged"]),
                "phase": "exec",
            },
        )

        return status_data

    def exec_fallback(self, prep_res: str, exc: Exception) -> dict[str, Any]:
        """Handle final failure after all retries with user-friendly messages."""
        cwd = prep_res

        logger.error(
            f"Failed to get git status after {self.max_retries} retries",
            extra={"working_directory": cwd, "error": str(exc), "phase": "fallback"},
        )

        # Provide specific error messages based on exception type
        error_msg = ""
        if isinstance(exc, ValueError) and "not a git repository" in str(exc):
            error_msg = f"Error: Directory '{cwd}' is not a git repository. Please run this command from within a git repository."
        elif isinstance(exc, subprocess.TimeoutExpired):
            error_msg = "Error: Git status command timed out after 30 seconds. The repository may be very large or there may be system issues."
        elif isinstance(exc, subprocess.CalledProcessError):
            error_msg = f"Error: Git command failed with exit code {exc.returncode}. {exc.stderr if exc.stderr else 'Unknown error'}"
        elif isinstance(exc, FileNotFoundError):
            error_msg = "Error: Git is not installed or not available in PATH. Please install git and try again."
        else:
            error_msg = f"Error: Could not get git status after {self.max_retries} retries. {exc!s}"

        # Return a status dict with the error message
        return {
            "modified": [],
            "untracked": [],
            "staged": [],
            "branch": "unknown",
            "ahead": 0,
            "behind": 0,
            "error": error_msg,
        }

    def post(self, shared: dict[str, Any], prep_res: str, exec_res: dict[str, Any]) -> Optional[str]:
        """Update shared store with git status and return action."""
        # Store the git status in shared store
        shared["git_status"] = exec_res

        # Log if there was an error
        if "error" in exec_res:
            logger.error("Git status failed", extra={"error": exec_res["error"], "phase": "post"})

        # Always return default action
        return "default"
