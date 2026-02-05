"""CLI command group for managing AI agent skills.

Publishes saved workflows as skills for various AI coding tools by enriching
the workflow file and creating symlinks from tool-specific skill directories.
"""

import sys
from pathlib import Path
from typing import Callable, TypeVar

import click

from pflow.core.skill_service import (
    DEFAULT_TARGET,
    SKILL_TARGETS,
    TARGET_LABELS,
    SkillInfo,
    create_skill_symlink,
    enrich_workflow,
    find_pflow_skills,
    find_skill_for_workflow,
)
from pflow.core.skill_service import (
    remove_skill as remove_skill_service,
)
from pflow.core.workflow_manager import WorkflowManager

F = TypeVar("F", bound=Callable[..., None])


def _get_target_help(target: str, action: str) -> str:
    """Generate help text for a target flag from SKILL_TARGETS config."""
    project_subdir, personal_subdir = SKILL_TARGETS[target]
    label = TARGET_LABELS[target]
    if project_subdir == personal_subdir:
        return f"{action} {label} ({project_subdir}/)"
    return f"{action} {label} ({project_subdir}/ or ~/{personal_subdir}/)"


def target_options(action: str) -> Callable[[F], F]:
    """Decorator that adds --personal, --cursor, --codex, --copilot options.

    Args:
        action: Verb for help text (e.g., "Save to", "Remove from")
    """

    def decorator(func: F) -> F:
        # Apply options in reverse order so they appear in the right order in --help
        func = click.option(
            "--copilot",
            is_flag=True,
            help=_get_target_help("copilot", action),
        )(func)
        func = click.option(
            "--codex",
            is_flag=True,
            help=_get_target_help("codex", action),
        )(func)
        func = click.option(
            "--cursor",
            is_flag=True,
            help=_get_target_help("cursor", action),
        )(func)
        func = click.option(
            "--personal",
            is_flag=True,
            help=f"{action} personal skills instead of project",
        )(func)
        return func

    return decorator


def _get_targets_from_flags(cursor: bool, codex: bool, copilot: bool) -> list[str]:
    """Convert target flags to list of targets, defaulting to claude."""
    targets = [t for t, enabled in [("cursor", cursor), ("codex", codex), ("copilot", copilot)] if enabled]
    return targets or [DEFAULT_TARGET]


def _format_target_label(target: str, scope: str) -> str:
    """Format target and scope for display."""
    label = TARGET_LABELS.get(target, target)
    project_subdir, personal_subdir = SKILL_TARGETS[target]
    path = f"~/{personal_subdir}/" if scope == "personal" else f"{project_subdir}/"
    return f"{label} ({path})"


def _build_group_help() -> str:
    """Build the skill group help text from SKILL_TARGETS config."""
    lines = [
        "Publish workflows as AI agent skills.",
        "",
        "Skills make workflows discoverable by AI coding tools. The saved workflow",
        "in ~/.pflow/workflows/ is the source of truth - skills are just symlinks.",
        "",
        "Supported tools (use flags like --cursor, --copilot):",
        "",
        "\b",  # Click directive to preserve formatting
    ]
    # Build table from config
    for target in SKILL_TARGETS:
        label = TARGET_LABELS[target]
        if target == DEFAULT_TARGET:
            label += " (default)"
        project_subdir, personal_subdir = SKILL_TARGETS[target]
        lines.append(f"  {label:<22} {project_subdir + '/':<18} ~/{personal_subdir}/")
    return "\n".join(lines)


@click.group(name="skill", help=_build_group_help())
def skill() -> None:
    """Publish workflows as AI agent skills."""


@skill.command(name="save")
@click.argument("workflow_name")
@target_options("Save to")
def save_skill(workflow_name: str, personal: bool, cursor: bool, codex: bool, copilot: bool) -> None:
    """Publish a saved workflow as an AI agent skill.

    Creates symlinks from tool skill directories to the saved workflow,
    and enriches the workflow file with skill metadata.

    By default, saves to Claude Code. Use --cursor, --codex, --copilot
    to save to other tools (can combine multiple).

    If the skill already exists, re-enriches the workflow file (idempotent).

    WORKFLOW_NAME is the name of a saved workflow (from 'pflow workflow save').
    """
    scope = "personal" if personal else "project"
    targets = _get_targets_from_flags(cursor, codex, copilot)

    manager = WorkflowManager()

    # Validate workflow exists
    if not manager.exists(workflow_name):
        click.echo(
            f"Error: Workflow '{workflow_name}' not found.\n"
            f"Save it first with: pflow workflow save <file> --name {workflow_name}",
            err=True,
        )
        sys.exit(1)

    # Load workflow data
    workflow_data = manager.load(workflow_name)
    workflow_path = Path(manager.get_path(workflow_name))

    # Enrich the workflow file once (idempotent — replaces existing ## Usage)
    enrich_workflow(
        workflow_path=workflow_path,
        name=workflow_name,
        description=workflow_data.get("description", ""),
        ir=workflow_data.get("ir", {}),
    )

    # Create symlinks for each target
    results: list[tuple[str, str, Path, bool]] = []  # (target, scope, path, was_new)
    errors: list[tuple[str, str]] = []  # (target, error_msg)

    for target in targets:
        # Check if skill already exists
        existing = find_skill_for_workflow(
            workflow_name,
            workflows_dir=manager.workflows_dir,
            targets=[target],
        )
        existing_in_scope = [s for s in existing if s.scope == scope]
        skill_exists = bool(existing_in_scope)

        try:
            if not skill_exists:
                symlink_path = create_skill_symlink(
                    workflow_path=workflow_path,
                    skill_name=workflow_name,
                    scope=scope,
                    target=target,
                )
                results.append((target, scope, symlink_path, True))
            else:
                results.append((target, scope, existing_in_scope[0].symlink_path, False))
        except Exception as e:
            errors.append((target, str(e)))

    # Display results
    for target, scope, symlink_path, was_new in results:
        target_label = _format_target_label(target, scope)
        if was_new:
            click.echo(f"Published '{workflow_name}' to {target_label}")
        else:
            click.echo(f"Updated '{workflow_name}' in {target_label}")
        click.echo(f"  Symlink: {symlink_path}")

    if results:
        click.echo(f"  Source:  {workflow_path}")

    # Display errors
    for target, error_msg in errors:
        click.echo(f"Error saving to {TARGET_LABELS.get(target, target)}: {error_msg}", err=True)

    if errors and not results:
        sys.exit(1)


def _workflow_name_from_skill(s: SkillInfo) -> str:
    """Extract workflow name from skill's target path."""
    name = s.target_path.stem
    return name[:-6] if name.endswith(".pflow") else name


def _show_broken_link_help(broken: SkillInfo) -> None:
    """Show help text for fixing a broken skill link."""
    workflow_name = _workflow_name_from_skill(broken)

    # Build flags for remove command
    flags = ""
    if broken.target != DEFAULT_TARGET:
        flags += f" --{broken.target}"
    if broken.scope == "personal":
        flags += " --personal"

    click.echo(f"Broken link: the source workflow '{workflow_name}' was deleted.")
    click.echo(f"  To restore: pflow workflow save <file> --name {workflow_name} --force")
    click.echo(f"  To remove:  pflow skill remove {workflow_name}{flags}")


@skill.command(name="list")
def list_skills() -> None:
    """List pflow-managed skills across all tools."""
    skills = find_pflow_skills()

    if not skills:
        click.echo("No pflow skills found.")
        return

    # Group skills by workflow name
    from collections import defaultdict

    by_workflow: dict[str, list[SkillInfo]] = defaultdict(list)
    for s in skills:
        by_workflow[_workflow_name_from_skill(s)].append(s)

    click.echo("pflow skills:\n")
    first_broken: SkillInfo | None = None

    for workflow_name in sorted(by_workflow.keys()):
        click.echo(f"  {workflow_name}")
        for s in by_workflow[workflow_name]:
            target_label = TARGET_LABELS.get(s.target, s.target)
            scope_label = "personal" if s.scope == "personal" else "project"
            status = "" if s.is_valid else " [broken link]"
            click.echo(f"    → {target_label} ({scope_label}){status}")
            if not s.is_valid and first_broken is None:
                first_broken = s
        click.echo()  # Blank line between workflows

    if first_broken:
        _show_broken_link_help(first_broken)


@skill.command(name="remove")
@click.argument("workflow_name")
@target_options("Remove from")
def remove_skill_cmd(workflow_name: str, personal: bool, cursor: bool, codex: bool, copilot: bool) -> None:
    """Remove a workflow's skill from tool directories.

    Removes symlinks from the specified tool directories. The saved workflow
    is left unchanged (enrichment is harmless).

    By default, removes from Claude Code. Use --cursor, --codex, --copilot
    to remove from other tools (can combine multiple).

    WORKFLOW_NAME is the name of the skill to remove.
    """
    scope = "personal" if personal else "project"
    targets = _get_targets_from_flags(cursor, codex, copilot)

    removed: list[str] = []
    not_found: list[str] = []

    for target in targets:
        if remove_skill_service(workflow_name, scope, target):
            removed.append(target)
        else:
            not_found.append(target)

    # Display results
    for target in removed:
        target_label = _format_target_label(target, scope)
        click.echo(f"Removed skill '{workflow_name}' from {target_label}")

    for target in not_found:
        target_label = _format_target_label(target, scope)
        click.echo(f"Skill '{workflow_name}' not found in {target_label}", err=True)

    if not_found and not removed:
        sys.exit(1)
