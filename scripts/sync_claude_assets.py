#!/usr/bin/env python3
"""Synchronize Claude-authored reusable assets into Codex's local formats."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

FRONTMATTER = re.compile(r"\A---\n(?P<metadata>.*?)\n---\n?", re.DOTALL)
TRIPLE_LITERAL_QUOTE = "'''"
CLAUDE_COMMAND_INPUT = "$ARGUMENTS"
CLAUDE_COMMAND_AGENT = re.compile(r"@agent-([A-Za-z0-9_-]+)")
CLAUDE_COMMAND_AUTORUN = re.compile(r"^!`(?P<command>[^`]+)`$", re.MULTILINE)
CLAUDE_AGENT_MODEL_TO_CODEX = {
    "fable": "gpt-5.6-sol",
    "opus": "gpt-5.6-sol",
    "sonnet": "gpt-5.6-terra",
}
CLAUDE_AGENT_EFFORT_TO_CODEX = {
    "low": "low",
    "medium": "medium",
    "high": "high",
}


@dataclass
class SyncResult:
    changed: list[Path] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def split_frontmatter(content: str, source: Path) -> tuple[str, str]:
    match = FRONTMATTER.match(content)
    if match is None:
        raise ValueError(f"{source}: expected YAML frontmatter")
    return match.group("metadata"), content[match.end() :]


def optional_metadata_value(metadata: str, key: str) -> str | None:
    prefix = f"{key}:"
    for line in metadata.splitlines():
        if line.startswith(prefix):
            value = line[len(prefix) :].strip()
            if len(value) >= 2 and value[0] == value[-1] == '"':
                decoded = json.loads(value)
                if not isinstance(decoded, str):
                    raise ValueError(f"frontmatter {key!r} must decode to a string")
                return decoded
            return value
    return None


def metadata_value(metadata: str, key: str, source: Path) -> str:
    value = optional_metadata_value(metadata, key)
    if value is not None:
        return value
    raise ValueError(f"{source}: frontmatter is missing {key!r}")


def mapped_agent_metadata(
    metadata: str,
    key: str,
    mapping: dict[str, str],
    source: Path,
) -> str | None:
    value = optional_metadata_value(metadata, key)
    if value is None:
        return None
    try:
        return mapping[value]
    except KeyError as error:
        supported = ", ".join(sorted(mapping))
        raise ValueError(f"{source}: unsupported agent {key} {value!r}; expected one of: {supported}") from error


def render_skill(source: Path, name: str | None = None) -> str:
    metadata, body = split_frontmatter(source.read_text(encoding="utf-8"), source)
    skill_name = name or metadata_value(metadata, "name", source)
    description = metadata_value(metadata, "description", source)
    return f"---\nname: {json.dumps(skill_name)}\ndescription: {json.dumps(description)}\n---\n{body}"


def render_command_skill(source: Path) -> str:
    """Render a Claude command as a Codex skill without changing its source."""
    metadata, body = split_frontmatter(source.read_text(encoding="utf-8"), source)
    body = translate_command_arguments(body)
    body = body.replace("{{task_id}}", "<task_id>")
    body = CLAUDE_COMMAND_AGENT.sub(r"\1", body)
    body = CLAUDE_COMMAND_AUTORUN.sub(
        lambda match: f"Run this command before proceeding:\n\n```bash\n{match.group('command')}\n```",
        body,
    )
    description = metadata_value(metadata, "description", source)
    return f"---\nname: {json.dumps(source.stem)}\ndescription: {json.dumps(description)}\n---\n{body}"


def translate_command_arguments(body: str) -> str:
    """Replace Claude's argument macro while preserving prose and shell intent."""
    body = body.replace("task_description='$ARGUMENTS'", "task_description='THE TASK DESCRIPTION'")
    body = body.replace("If `$ARGUMENTS` is empty", "If the user has not supplied a task description")
    body = body.replace(
        "--use-parallel-subagents=$ARGUMENTS (default: false)",
        "Read the optional `--use-parallel-subagents=<true|false>` flag from the user's request (default: false).",
    )
    body = body.replace("Inputs: $ARGUMENTS", "Inputs: derive them from the user's request.")
    body = re.sub(r"(?m)^\$ARGUMENTS$", "Use the user's request as the input.", body)
    body = body.replace("`$ARGUMENTS`", "the user's request")
    return body.replace(CLAUDE_COMMAND_INPUT, "the user's request")


def render_agent(source: Path) -> str:
    metadata, body = split_frontmatter(source.read_text(encoding="utf-8"), source)
    if TRIPLE_LITERAL_QUOTE in body:
        raise ValueError(f"{source}: instructions contain {TRIPLE_LITERAL_QUOTE!r}")
    name = metadata_value(metadata, "name", source)
    description = metadata_value(metadata, "description", source)
    model = mapped_agent_metadata(metadata, "model", CLAUDE_AGENT_MODEL_TO_CODEX, source)
    effort = mapped_agent_metadata(metadata, "effort", CLAUDE_AGENT_EFFORT_TO_CODEX, source)
    lines = [f"name = {json.dumps(name)}", f"description = {json.dumps(description)}"]
    if model is not None:
        lines.append(f"model = {json.dumps(model)}")
    if effort is not None:
        lines.append(f"model_reasoning_effort = {json.dumps(effort)}")
    lines.extend((
        f"developer_instructions = {TRIPLE_LITERAL_QUOTE}",
        f"{body}{TRIPLE_LITERAL_QUOTE}",
    ))
    return "\n".join(lines) + "\n"


def ensure_content(target: Path, expected: str, write: bool, result: SyncResult) -> None:
    if target.is_file() and target.read_text(encoding="utf-8") == expected:
        return
    if not write:
        result.errors.append(f"Generated asset is stale: {target}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(expected, encoding="utf-8")
    result.changed.append(target)


def synchronize_skill(source_dir: Path, target_dir: Path, write: bool, result: SyncResult) -> None:
    source_files = {path.relative_to(source_dir) for path in source_dir.rglob("*") if path.is_file()}
    if Path("SKILL.md") not in source_files:
        raise ValueError(f"{source_dir}: expected SKILL.md")

    for relative_path in source_files:
        source = source_dir / relative_path
        target = target_dir / relative_path
        expected = render_skill(source) if relative_path == Path("SKILL.md") else source.read_text(encoding="utf-8")
        ensure_content(target, expected, write, result)

    if not target_dir.exists():
        return
    target_files = {path.relative_to(target_dir) for path in target_dir.rglob("*") if path.is_file()}
    for relative_path in target_files - source_files:
        target = target_dir / relative_path
        if not write:
            result.errors.append(f"Generated asset no longer exists in Claude source: {target}")
            continue
        target.unlink()
        result.changed.append(target)

    if write:
        for directory in sorted((path for path in target_dir.rglob("*") if path.is_dir()), reverse=True):
            if not any(directory.iterdir()):
                directory.rmdir()


def synchronize(root: Path, write: bool) -> SyncResult:
    result = SyncResult()

    skills_source = root / ".claude/skills"
    skill_dirs = sorted(path for path in skills_source.iterdir() if path.is_dir())
    commands_source = root / ".claude/commands"
    commands = sorted(commands_source.glob("*.md"))
    collisions = sorted({source_dir.name for source_dir in skill_dirs} & {source.stem for source in commands})
    if collisions:
        result.errors.extend(
            f"Claude skill and command share generated Codex skill name: {name}" for name in collisions
        )
        return result

    for source_dir in skill_dirs:
        synchronize_skill(source_dir, root / ".agents/skills" / source_dir.name, write, result)

    agents_source = root / ".claude/agents"
    protocol_source = agents_source / "REVIEW-PROTOCOL.md"
    ensure_content(
        root / ".codex/agents/REVIEW-PROTOCOL.md",
        protocol_source.read_text(encoding="utf-8"),
        write,
        result,
    )
    for source in sorted(agents_source.glob("*.md")):
        if source == protocol_source:
            continue
        ensure_content(root / ".codex/agents" / f"{source.stem}.toml", render_agent(source), write, result)

    for source in commands:
        target = root / ".agents/skills" / source.stem / "SKILL.md"
        ensure_content(target, render_command_skill(source), write, result)

    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="Report stale assets without modifying files.")
    mode.add_argument("--write", action="store_true", help="Regenerate generated Codex assets.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parent.parent
    result = synchronize(root, write=args.write)
    if result.errors:
        print("Claude/Codex asset synchronization failed:", file=sys.stderr)
        print(*result.errors, sep="\n", file=sys.stderr)
        return 1
    if args.write:
        print(f"Synchronized {len(result.changed)} Claude/Codex asset files.")
    else:
        print("Claude/Codex assets are in sync.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
