"""Skill service for publishing workflows as AI agent skills.

Handles enrichment of saved workflow files (frontmatter + Usage section),
symlink management between ~/.pflow/workflows/ and various tool skill directories,
and scanning for pflow-managed skills.

Supported targets:
- Claude Code: .claude/skills/ (project), ~/.claude/skills/ (personal)
- Cursor: .cursor/skills/ (project), ~/.cursor/skills/ (personal)
- Codex: .agents/skills/ (project), ~/.agents/skills/ (personal)
- Copilot: .github/skills/ (project), ~/.copilot/skills/ (personal)
"""

import logging
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from pflow.core.workflow_manager import WorkflowManager

logger = logging.getLogger(__name__)

# Skill target configurations: target -> (project_subdir, personal_subdir)
SKILL_TARGETS: dict[str, tuple[str, str]] = {
    "claude": (".claude/skills", ".claude/skills"),
    "cursor": (".cursor/skills", ".cursor/skills"),
    "codex": (".agents/skills", ".agents/skills"),
    "copilot": (".github/skills", ".copilot/skills"),
}

# Human-readable names for output
TARGET_LABELS: dict[str, str] = {
    "claude": "Claude Code",
    "cursor": "Cursor",
    "codex": "Codex",
    "copilot": "Copilot",
}

DEFAULT_TARGET = "claude"


@dataclass
class SkillInfo:
    """Information about a pflow-managed skill."""

    name: str
    scope: str  # "project" or "personal"
    target: str  # "claude", "cursor", "codex", "copilot"
    symlink_path: Path
    target_path: Path
    is_valid: bool  # symlink resolves to existing file


def generate_usage_section(workflow_name: str, ir: dict[str, Any]) -> str:
    """Generate the ## Usage markdown section from workflow IR inputs.

    Builds a usage section with an example pflow command showing required
    parameters. Stdin inputs are excluded (they're piped, not CLI args).

    Args:
        workflow_name: Name of the workflow
        ir: Workflow IR containing inputs specification

    Returns:
        Complete ## Usage section as markdown string
    """
    # Collect required parameters, excluding stdin inputs
    example_params: list[str] = []
    inputs = ir.get("inputs", {})
    for input_name, config in inputs.items():
        if not isinstance(config, dict):
            continue
        # Skip stdin inputs — they're piped, not CLI args
        if config.get("stdin") is True:
            continue
        if config.get("required", True):
            example_params.append(f"{input_name}=<value>")

    # Build example command
    command = f"pflow {workflow_name}"
    if example_params:
        command += f" {' '.join(example_params)}"

    return f"""## Usage

If you are unsure this is exactly what the user wants to execute, ask the user if they want to run this workflow. If any required inputs are missing, ask the user to provide them.
Always ask the user before modifying or extending the workflow or reading the instructions.

```bash
# Execute this workflow directly:
{command}

# View execution history and last used inputs:
pflow workflow history {workflow_name}

# To modify or extend - read all 3 parts IN FULL (do not truncate):
pflow instructions create --part 1
pflow instructions create --part 2
pflow instructions create --part 3
```

> Pflow and all dependencies should be installed, working and ready to use.

---"""


def _inject_or_replace_usage(body: str, usage_section: str) -> str:
    """Inject or replace ## Usage section in the markdown body.

    Injection point: after H1 prose, before first ## section.
    Replacement: finds existing ## Usage and replaces up to next ##.

    Args:
        body: Markdown body (without frontmatter)
        usage_section: The complete ## Usage section to inject

    Returns:
        Modified body with ## Usage section
    """
    # Check for existing ## Usage
    usage_match = re.search(r"^## Usage\b.*$", body, re.MULTILINE)
    if usage_match:
        # Replace existing ## Usage section
        rest = body[usage_match.end() :]
        next_section = re.search(r"^## ", rest, re.MULTILINE)
        end_pos = usage_match.end() + next_section.start() if next_section else len(body)
        body = body[: usage_match.start()] + usage_section + "\n\n" + body[end_pos:].lstrip("\n")
    else:
        # Inject before first ## section
        first_section = re.search(r"^## ", body, re.MULTILINE)
        if first_section:
            insert_pos = first_section.start()
            body = body[:insert_pos] + usage_section + "\n\n" + body[insert_pos:]
        else:
            # No ## sections at all — append
            body = body.rstrip() + "\n\n" + usage_section + "\n"

    return body


def enrich_workflow(workflow_path: Path, name: str, description: str, ir: dict[str, Any]) -> None:
    """Enrich a saved workflow file with skill metadata.

    Adds name and description to YAML frontmatter and injects/replaces
    the ## Usage section in the markdown body.

    Args:
        workflow_path: Path to the saved workflow file
        name: Workflow name (for frontmatter and usage section)
        description: Workflow description (for frontmatter)
        ir: Workflow IR (for generating usage section)
    """
    manager = WorkflowManager()

    content = workflow_path.read_text(encoding="utf-8")
    frontmatter, body = manager._split_frontmatter_and_body(content)

    # Add name and description at TOP of frontmatter (Claude Code reads these first)
    # Note: description in frontmatter is needed for Claude Code skill discovery.
    # There's currently a bug requiring it for skill discovery (short-term workaround).
    # When the bug is fixed, description remains useful for auto-invocation.
    frontmatter = {"name": name, "description": description, **frontmatter}

    # Generate and inject/replace ## Usage section
    usage_section = generate_usage_section(name, ir)
    body = _inject_or_replace_usage(body, usage_section)

    # Reassemble and write atomically
    new_content = manager._serialize_with_frontmatter(frontmatter, body)

    temp_fd, temp_path = tempfile.mkstemp(
        dir=workflow_path.parent,
        prefix=f".{name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
            f.write(new_content)
        os.replace(temp_path, workflow_path)
        logger.info(f"Enriched workflow '{name}' at {workflow_path}")
    except Exception:
        Path(temp_path).unlink(missing_ok=True)
        raise


def _get_skills_base_dir(
    scope: str,
    target: str = DEFAULT_TARGET,
    project_dir: Optional[Path] = None,
) -> Path:
    """Get the base directory for skills based on scope and target.

    Args:
        scope: "project" or "personal"
        target: Tool target ("claude", "cursor", "codex", "copilot")
        project_dir: Project directory (defaults to cwd)

    Returns:
        Base path for skills directory (e.g., .claude/skills/, .cursor/skills/)
    """
    if target not in SKILL_TARGETS:
        raise ValueError(f"Unknown target '{target}'. Valid targets: {', '.join(SKILL_TARGETS.keys())}")

    project_subdir, personal_subdir = SKILL_TARGETS[target]

    if scope == "personal":
        return Path.home() / personal_subdir
    else:
        base = project_dir or Path.cwd()
        return base / project_subdir


def create_skill_symlink(
    workflow_path: Path,
    skill_name: str,
    scope: str,
    target: str = DEFAULT_TARGET,
    project_dir: Optional[Path] = None,
) -> Path:
    """Create a symlink from a tool's skills directory to the saved workflow.

    Creates: {base}/{skills_dir}/{skill_name}/SKILL.md -> workflow_path

    Args:
        workflow_path: Absolute path to the saved workflow file
        skill_name: Name for the skill directory
        scope: "project" or "personal"
        target: Tool target ("claude", "cursor", "codex", "copilot")
        project_dir: Project directory (defaults to cwd)

    Returns:
        Path to the created symlink

    Raises:
        FileExistsError: If skill symlink already exists
    """
    skills_base = _get_skills_base_dir(scope, target, project_dir)
    skill_dir = skills_base / skill_name
    symlink_path = skill_dir / "SKILL.md"

    if symlink_path.exists() or symlink_path.is_symlink():
        raise FileExistsError(f"Skill '{skill_name}' already exists at {symlink_path}")

    # Create directory structure
    skill_dir.mkdir(parents=True, exist_ok=True)

    # Create symlink pointing to the workflow file
    symlink_path.symlink_to(workflow_path)
    logger.info(f"Created skill symlink: {symlink_path} -> {workflow_path}")

    return symlink_path


def remove_skill(
    skill_name: str,
    scope: str,
    target: str = DEFAULT_TARGET,
    project_dir: Optional[Path] = None,
) -> bool:
    """Remove a skill symlink and its parent directory.

    Args:
        skill_name: Name of the skill to remove
        scope: "project" or "personal"
        target: Tool target ("claude", "cursor", "codex", "copilot")
        project_dir: Project directory (defaults to cwd)

    Returns:
        True if removed, False if not found
    """
    skills_base = _get_skills_base_dir(scope, target, project_dir)
    skill_dir = skills_base / skill_name
    symlink_path = skill_dir / "SKILL.md"

    if not symlink_path.exists() and not symlink_path.is_symlink():
        return False

    # Remove symlink
    symlink_path.unlink()

    # Remove parent directory if empty
    import contextlib

    with contextlib.suppress(OSError):
        skill_dir.rmdir()  # Fails if not empty — that's fine

    logger.info(f"Removed skill '{skill_name}' from {target}/{scope}")
    return True


def _resolve_symlink_target(symlink_path: Path) -> Optional[Path]:
    """Resolve symlink target to absolute path, or None if unreadable."""
    try:
        target = Path(os.readlink(symlink_path))
        return (symlink_path.parent / target).resolve() if not target.is_absolute() else target.resolve()
    except OSError:
        return None


def _is_pflow_skill(target: Path, workflows_dir: Path) -> bool:
    """Check if target path is under the pflow workflows directory."""
    try:
        return target.resolve().is_relative_to(workflows_dir)
    except (ValueError, TypeError):
        return False


def find_pflow_skills(
    project_dir: Optional[Path] = None,
    workflows_dir: Optional[Path] = None,
    targets: Optional[list[str]] = None,
) -> list[SkillInfo]:
    """Scan skill directories for pflow-managed symlinks.

    Scans all tool targets (Claude, Cursor, Codex, Copilot) by default.
    Only returns skills that are symlinks pointing to ~/.pflow/workflows/.
    Non-pflow skills are ignored.

    Args:
        project_dir: Project directory (defaults to cwd)
        workflows_dir: Workflows directory (defaults to ~/.pflow/workflows/)
        targets: Tool targets to scan (defaults to all)

    Returns:
        List of SkillInfo sorted by (target, scope, name)
    """
    workflows_dir = workflows_dir.resolve() if workflows_dir else Path("~/.pflow/workflows").expanduser().resolve()
    targets_to_scan = targets if targets else list(SKILL_TARGETS.keys())

    skills: list[SkillInfo] = []

    for tool_target in targets_to_scan:
        for scope in ("project", "personal"):
            skills_base = _get_skills_base_dir(scope, tool_target, project_dir)
            if not skills_base.exists():
                continue

            for skill_dir in sorted(skills_base.iterdir()):
                symlink_path = skill_dir / "SKILL.md"
                if not skill_dir.is_dir() or not symlink_path.is_symlink():
                    continue

                resolved_target = _resolve_symlink_target(symlink_path)
                if resolved_target is None or not _is_pflow_skill(resolved_target, workflows_dir):
                    continue

                skills.append(
                    SkillInfo(
                        name=skill_dir.name,
                        scope=scope,
                        target=tool_target,
                        symlink_path=symlink_path,
                        target_path=resolved_target,
                        is_valid=resolved_target.exists(),
                    )
                )

    skills.sort(key=lambda s: (s.target, s.scope, s.name))
    return skills


def find_skill_for_workflow(
    workflow_name: str,
    project_dir: Optional[Path] = None,
    workflows_dir: Optional[Path] = None,
    targets: Optional[list[str]] = None,
) -> list[SkillInfo]:
    """Find skills that point to a specific workflow.

    Convenience wrapper around find_pflow_skills that filters by workflow name.

    Args:
        workflow_name: Workflow name to search for
        project_dir: Project directory (defaults to cwd)
        workflows_dir: Workflows directory (defaults to ~/.pflow/workflows/)
        targets: Tool targets to scan (defaults to all)

    Returns:
        List of SkillInfo matching the workflow name
    """
    all_skills = find_pflow_skills(project_dir=project_dir, workflows_dir=workflows_dir, targets=targets)
    target_filename = f"{workflow_name}.pflow.md"
    return [s for s in all_skills if s.target_path.name == target_filename]


def re_enrich_if_skill(
    workflow_name: str,
    project_dir: Optional[Path] = None,
) -> None:
    """Re-enrich a workflow if it's published as a skill.

    Called after workflow save --force to restore enrichment that was lost
    when the file was replaced. Scans both project and personal skill
    directories for symlinks pointing to the workflow.

    Args:
        workflow_name: Name of the workflow that was just saved
        project_dir: Project directory (defaults to cwd)
    """
    manager = WorkflowManager()

    if not manager.exists(workflow_name):
        return

    skills = find_skill_for_workflow(
        workflow_name,
        project_dir=project_dir,
        workflows_dir=manager.workflows_dir,
    )

    if not skills:
        return

    # Re-enrich the workflow
    workflow_data = manager.load(workflow_name)
    workflow_path = Path(manager.get_path(workflow_name))

    enrich_workflow(
        workflow_path=workflow_path,
        name=workflow_name,
        description=workflow_data.get("description", ""),
        ir=workflow_data.get("ir", {}),
    )

    logger.info(f"Re-enriched workflow '{workflow_name}' (skill detected in {len(skills)} scope(s))")
