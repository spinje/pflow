from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts/sync_claude_assets.py"
SPEC = importlib.util.spec_from_file_location("sync_claude_assets", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
sync_claude_assets = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = sync_claude_assets
SPEC.loader.exec_module(sync_claude_assets)


def write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def read_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def make_root(tmp_path: Path) -> Path:
    skill = (
        "---\nname: demo-skill\ndescription: Demo skill\nargument-hint: ignored\n---\n\n# Demo\n\n● TIGHT dependency.\n"
    )
    agent = "---\nname: demo-agent\ndescription: Demo agent\nmodel: ignored\n---\n\nDo the work. 🔍\n"
    command = (
        "---\ndescription: Demo command\nargument-hint: ignored\n---\n\nDo the command.\n\nPreserve “smart quotes”.\n"
    )

    write_file(tmp_path / ".claude/skills/demo-skill/SKILL.md", skill)
    write_file(tmp_path / ".claude/skills/demo-skill/reference.md", "Reference with café text.\n")
    write_file(tmp_path / ".claude/agents/REVIEW-PROTOCOL.md", "Protocol.\n")
    write_file(tmp_path / ".claude/agents/demo-agent.md", agent)
    write_file(tmp_path / ".claude/commands/demo-command.md", command)
    return tmp_path


def test_write_generates_codex_assets(tmp_path: Path) -> None:
    root = make_root(tmp_path)

    result = sync_claude_assets.synchronize(root, write=True)

    assert result.errors == []
    assert read_file(root / ".agents/skills/demo-skill/reference.md") == "Reference with café text.\n"
    assert read_file(root / ".agents/skills/demo-skill/SKILL.md").startswith(
        '---\nname: "demo-skill"\ndescription: "Demo skill"\n---\n'
    )
    assert read_file(root / ".agents/skills/demo-command/SKILL.md").startswith(
        '---\nname: "demo-command"\ndescription: "Demo command"\n---\n'
    )
    agent = read_file(root / ".codex/agents/demo-agent.toml")
    assert 'description = "Demo agent"' in agent
    assert "developer_instructions = '''" in agent
    assert 'name = "demo-agent"' in agent
    assert "Do the work. 🔍" in agent
    assert "● TIGHT dependency." in read_file(root / ".agents/skills/demo-skill/SKILL.md")
    assert "Preserve “smart quotes”." in read_file(root / ".agents/skills/demo-command/SKILL.md")


def test_check_reports_generated_asset_drift(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    sync_claude_assets.synchronize(root, write=True)
    write_file(root / ".agents/skills/demo-command/SKILL.md", "stale\n")

    result = sync_claude_assets.synchronize(root, write=False)

    assert result.changed == []
    assert result.errors == ["Generated asset is stale: " + str(root / ".agents/skills/demo-command/SKILL.md")]


def test_write_translates_claude_only_command_syntax(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    command = root / ".claude/commands/demo-command.md"
    command.write_text(
        read_file(command).replace(
            "Do the command.",
            "Inputs: $ARGUMENTS\ntask_description='$ARGUMENTS'\n!`git branch --show-current`\n@agent-demo\n{{task_id}}",
        ),
        encoding="utf-8",
    )

    result = sync_claude_assets.synchronize(root, write=True)

    assert result.errors == []
    rendered = read_file(root / ".agents/skills/demo-command/SKILL.md")
    assert "$ARGUMENTS" not in rendered
    assert "@agent-demo" not in rendered
    assert "{{task_id}}" not in rendered
    assert "Inputs: derive them from the user's request." in rendered
    assert "task_description='THE TASK DESCRIPTION'" in rendered
    assert "Run this command before proceeding:\n\n```bash\ngit branch --show-current\n```" in rendered
    assert "demo\n<task_id>" in rendered


def test_rejects_skill_command_name_collision(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    write_file(
        root / ".claude/skills/demo-command/SKILL.md",
        "---\nname: demo-command\ndescription: Conflicting skill\n---\n",
    )

    result = sync_claude_assets.synchronize(root, write=True)

    assert result.changed == []
    assert result.errors == ["Claude skill and command share generated Codex skill name: demo-command"]
