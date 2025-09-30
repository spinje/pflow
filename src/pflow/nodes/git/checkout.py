"""Git checkout node implementation."""

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


class GitCheckoutNode(Node):
    """
    Create or switch to a git branch.

    Interface:
    - Reads: shared["branch"]: str  # Branch name to create or switch to
    - Reads: shared["create"]: bool  # Create new branch (optional, default: false)
    - Reads: shared["base"]: str  # Base branch for new branch (optional, default: current branch)
    - Reads: shared["force"]: bool  # Force create even if exists (optional, default: false)
    - Reads: shared["stash"]: bool  # Auto-stash uncommitted changes (optional, default: false)
    - Reads: shared["working_directory"]: str  # Directory to run git commands (optional, default: current directory)
    - Writes: shared["current_branch"]: str  # Name of the branch after checkout
    - Writes: shared["previous_branch"]: str  # Name of the branch before checkout
    - Writes: shared["branch_created"]: bool  # Whether a new branch was created
    - Writes: shared["stash_created"]: str  # Stash reference if changes were stashed
    - Actions: default (always)

    Note:
        This node operates on the current working directory only.
        It cannot target remote repositories like GitHub nodes can.
        Protected branches (main, master, develop, production, staging) cannot be created
        unless the force flag is set.
    """

    name = "git-checkout"  # CRITICAL: Required for registry discovery

    def __init__(self) -> None:
        """Initialize with retry support for transient git issues."""
        super().__init__(max_retries=2, wait=0.5)

    def _get_current_branch(self, cwd: str) -> str:
        """Get the current branch name.

        Args:
            cwd: Working directory path

        Returns:
            Current branch name or empty string if detached HEAD

        Raises:
            subprocess.CalledProcessError: If git command fails
            ValueError: If not in a git repository
        """
        cmd = ["git", "branch", "--show-current"]
        result = subprocess.run(  # noqa: S603
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            shell=False,
            timeout=10,
            check=False,
        )

        if result.returncode != 0:
            if "not a git repository" in result.stderr.lower():
                raise ValueError(f"Directory '{cwd}' is not a git repository")
            # Could be detached HEAD state, try alternate method
            cmd_alt = ["git", "rev-parse", "--abbrev-ref", "HEAD"]
            result_alt = subprocess.run(  # noqa: S603
                cmd_alt,
                cwd=cwd,
                capture_output=True,
                text=True,
                shell=False,
                timeout=10,
                check=False,
            )
            if result_alt.returncode == 0:
                branch = result_alt.stdout.strip()
                return "" if branch == "HEAD" else branch  # HEAD means detached

            raise subprocess.CalledProcessError(
                result.returncode, result.args, output=result.stdout, stderr=result.stderr
            )

        return result.stdout.strip()

    def _has_uncommitted_changes(self, cwd: str) -> bool:
        """Check if there are uncommitted changes in the repository.

        Args:
            cwd: Working directory path

        Returns:
            True if there are uncommitted changes, False otherwise
        """
        cmd = ["git", "status", "--porcelain"]
        result = subprocess.run(  # noqa: S603
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            shell=False,
            timeout=10,
            check=False,
        )

        return bool(result.stdout.strip())

    def _branch_exists(self, branch: str, cwd: str) -> bool:
        """Check if a branch exists locally.

        Args:
            branch: Branch name to check
            cwd: Working directory path

        Returns:
            True if branch exists, False otherwise
        """
        cmd = ["git", "rev-parse", "--verify", f"refs/heads/{branch}"]
        result = subprocess.run(  # noqa: S603
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            shell=False,
            timeout=10,
            check=False,
        )

        return result.returncode == 0

    def _is_protected_branch(self, branch: str, protected_branches: list[str]) -> bool:
        """Check if a branch name is protected.

        Args:
            branch: Branch name to check
            protected_branches: List of protected branch names

        Returns:
            True if branch is protected, False otherwise
        """
        return branch.lower() in [pb.lower() for pb in protected_branches]

    def _stash_changes(self, cwd: str, message: str) -> str:
        """Stash uncommitted changes.

        Args:
            cwd: Working directory path
            message: Stash message

        Returns:
            Stash reference (e.g., "stash@{0}") or empty string if nothing to stash

        Raises:
            subprocess.CalledProcessError: If stash command fails
        """
        cmd = ["git", "stash", "push", "-m", message]
        result = subprocess.run(  # noqa: S603
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            shell=False,
            timeout=30,
            check=False,
        )

        if result.returncode != 0:
            if "no local changes to save" in result.stdout.lower():
                return ""
            raise subprocess.CalledProcessError(
                result.returncode, result.args, output=result.stdout, stderr=result.stderr
            )

        # Extract stash reference from output
        match = re.search(r"stash@\{(\d+)\}", result.stdout)
        if match:
            return f"stash@{{{match.group(1)}}}"

        # Fallback to most recent stash
        return "stash@{0}" if "Saved working directory" in result.stdout else ""

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        """Extract branch parameters from shared store or parameters."""
        # Get branch name from shared or params
        branch = shared.get("branch") or self.params.get("branch")
        if not branch:
            raise ValueError("Branch name is required. Provide it in shared['branch'] or as a parameter.")

        # Validate branch name (basic sanitization)
        if not re.match(r"^[\w\-/.]+$", branch):
            raise ValueError(
                f"Invalid branch name '{branch}'. Use only alphanumeric characters, hyphens, slashes, and dots."
            )

        # Get operation flags
        create = shared.get("create") or self.params.get("create", False)
        base = shared.get("base") or self.params.get("base")
        force = shared.get("force") or self.params.get("force", False)
        stash = shared.get("stash") or self.params.get("stash", False)

        # Get working directory
        cwd = shared.get("working_directory") or self.params.get("working_directory", ".")
        cwd = Path(cwd).expanduser().resolve()

        # Get protected branches list
        protected = self.params.get("protected_branches", [])
        default_protected = ["main", "master", "develop", "production", "staging"]
        protected_branches = default_protected + protected

        logger.debug(
            "Preparing to checkout branch",
            extra={
                "branch": branch,
                "create": create,
                "base": base,
                "force": force,
                "stash": stash,
                "working_directory": str(cwd),
                "phase": "prep",
            },
        )

        return {
            "branch": branch,
            "create": create,
            "base": base,
            "force": force,
            "stash": stash,
            "working_directory": str(cwd),
            "protected_branches": protected_branches,
        }

    def _handle_uncommitted_changes(self, branch: str, stash: bool, cwd: str) -> str:
        """Handle uncommitted changes by stashing if requested.

        Returns:
            Stash reference if stash was created, empty string otherwise
        """
        has_changes = self._has_uncommitted_changes(cwd)
        stash_ref = ""

        if has_changes:
            if stash:
                # Auto-stash changes
                logger.info("Stashing uncommitted changes")
                stash_message = f"Auto-stash before checkout to {branch}"
                try:
                    stash_ref = self._stash_changes(cwd, stash_message)
                    if stash_ref:
                        logger.info(f"Created stash: {stash_ref}")
                except subprocess.CalledProcessError as e:
                    raise ValueError(f"Failed to stash changes: {e.stderr if e.stderr else 'Unknown error'}") from e
            else:
                raise ValueError(
                    "Uncommitted changes detected. "
                    "Commit your changes, stash them manually, or set stash=true to auto-stash."
                )

        return stash_ref

    def _prepare_branch_creation(
        self,
        branch: str,
        base: str | None,
        force: bool,
        protected_branches: list[str],
        cwd: str,
        previous_branch: str | None,
    ) -> tuple[list[str], bool]:
        """Prepare for branch creation, including validation and base branch checkout.

        Returns:
            Tuple of (checkout command args, whether branch is being created)
        """
        # Check if creating a protected branch
        if self._is_protected_branch(branch, protected_branches) and not force:
            raise ValueError(
                f"Cannot create protected branch '{branch}'. "
                f"Protected branches: {', '.join(protected_branches)}. "
                f"Use force=true to override this protection."
            )

        # Check if branch already exists
        if self._branch_exists(branch, cwd) and not force:
            raise ValueError(
                f"Branch '{branch}' already exists. Use force=true to reset it or create=false to switch to it."
            )

        # Checkout base branch first if specified and different from current
        if base and base != previous_branch:
            logger.info(f"Checking out base branch '{base}' first")
            base_cmd = ["git", "checkout", base]
            base_result = subprocess.run(  # noqa: S603
                base_cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                shell=False,
                timeout=30,
                check=False,
            )

            if base_result.returncode != 0:
                error_msg = base_result.stderr.lower()
                if "did not match any file" in error_msg or "pathspec" in error_msg:
                    raise ValueError(f"Base branch '{base}' does not exist")
                raise ValueError(f"Failed to checkout base branch '{base}': {base_result.stderr}")

        # Create the new branch
        create_flag = "-B" if force else "-b"
        checkout_cmd = ["git", "checkout", create_flag, branch]
        logger.info(f"Creating new branch '{branch}'{' (force)' if force else ''}")

        return checkout_cmd, True

    def _execute_checkout(self, checkout_cmd: list[str], cwd: str, branch: str) -> None:
        """Execute the git checkout command and handle errors."""
        checkout_result = subprocess.run(  # noqa: S603
            checkout_cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            shell=False,
            timeout=30,
            check=False,
        )

        if checkout_result.returncode != 0:
            error_msg = checkout_result.stderr.lower()
            if "did not match any file" in error_msg or "pathspec" in error_msg:
                raise ValueError(f"Branch '{branch}' does not exist. Use create=true to create a new branch.")
            elif "already exists" in error_msg:
                raise ValueError(
                    f"Branch '{branch}' already exists. Use force=true to reset it or create=false to switch to it."
                )
            else:
                raise subprocess.CalledProcessError(
                    checkout_result.returncode,
                    checkout_result.args,
                    output=checkout_result.stdout,
                    stderr=checkout_result.stderr,
                )

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        """Execute branch checkout operation.

        Returns:
            Dictionary with checkout results

        Raises:
            ValueError: For validation errors
            subprocess.CalledProcessError: If git command fails
            subprocess.TimeoutExpired: If command takes too long
        """
        branch = prep_res["branch"]
        create = prep_res["create"]
        base = prep_res["base"]
        force = prep_res["force"]
        stash = prep_res["stash"]
        cwd = prep_res["working_directory"]
        protected_branches = prep_res["protected_branches"]

        logger.info(
            "Executing git checkout",
            extra={
                "branch": branch,
                "create": create,
                "base": base,
                "working_directory": cwd,
                "phase": "exec",
            },
        )

        # Get current branch first
        try:
            previous_branch = self._get_current_branch(cwd)
            if not previous_branch:
                logger.warning("Currently in detached HEAD state")
        except ValueError:
            # Re-raise with original message
            raise
        except subprocess.CalledProcessError as e:
            raise ValueError(f"Failed to get current branch: {e.stderr if e.stderr else 'Unknown error'}") from e

        # Handle uncommitted changes
        stash_ref = self._handle_uncommitted_changes(branch, stash, cwd)

        # Handle branch creation vs switching
        branch_created = False

        if create:
            checkout_cmd, branch_created = self._prepare_branch_creation(
                branch, base, force, protected_branches, cwd, previous_branch
            )
        else:
            # Just switch to existing branch
            checkout_cmd = ["git", "checkout", branch]
            logger.info(f"Switching to branch '{branch}'")

        # Execute the checkout command
        self._execute_checkout(checkout_cmd, cwd, branch)

        logger.info(
            "Branch checkout successful",
            extra={
                "branch": branch,
                "previous_branch": previous_branch,
                "created": branch_created,
                "stash_created": bool(stash_ref),
                "phase": "exec",
            },
        )

        return {
            "current_branch": branch,
            "previous_branch": previous_branch or "",
            "branch_created": branch_created,
            "stash_created": stash_ref,
            "status": "success",
        }

    def exec_fallback(self, prep_res: dict[str, Any], exc: Exception) -> dict[str, Any]:
        """Handle final failure after all retries with user-friendly messages."""
        branch = prep_res["branch"]
        cwd = prep_res["working_directory"]

        logger.error(
            f"Failed to checkout branch after {self.max_retries} retries",
            extra={"branch": branch, "working_directory": cwd, "error": str(exc), "phase": "fallback"},
        )

        # Provide specific error messages based on exception type
        error_msg = ""
        if isinstance(exc, ValueError):
            error_msg = str(exc)  # Our custom error messages are already user-friendly
        elif isinstance(exc, subprocess.TimeoutExpired):
            error_msg = "Error: Git checkout command timed out after 30 seconds. The repository may be very large or there may be system issues."
        elif isinstance(exc, subprocess.CalledProcessError):
            stderr_msg = exc.stderr if exc.stderr else "Unknown error"
            error_msg = f"Error: Git command failed with exit code {exc.returncode}. {stderr_msg}"
        elif isinstance(exc, FileNotFoundError):
            error_msg = "Error: Git is not installed or not available in PATH. Please install git and try again."
        else:
            error_msg = f"Error: Could not checkout branch after {self.max_retries} retries. {exc!s}"

        # Return a result dict with the error message
        return {
            "current_branch": "",
            "previous_branch": "",
            "branch_created": False,
            "stash_created": "",
            "status": "error",
            "error": error_msg,
        }

    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> Optional[str]:
        """Update shared store with checkout results and return action."""
        # Check for error status first
        if exec_res.get("status") == "error":
            shared["error"] = exec_res.get("error", "Git operation failed")
            shared["current_branch"] = exec_res.get("current_branch", "")
            shared["previous_branch"] = exec_res.get("previous_branch", "")
            shared["branch_created"] = False
            logger.error(
                "Branch checkout failed", extra={"error": exec_res.get("error", "Unknown error"), "phase": "post"}
            )
            return "error"  # Return error to trigger repair

        # Store results in shared store for success
        shared["current_branch"] = exec_res.get("current_branch", "")
        shared["previous_branch"] = exec_res.get("previous_branch", "")
        shared["branch_created"] = exec_res.get("branch_created", False)

        if exec_res.get("stash_created"):
            shared["stash_created"] = exec_res["stash_created"]

        return "default"
