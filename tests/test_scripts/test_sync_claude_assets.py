from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised by the Python 3.10 CI leg
    import tomli as tomllib

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
    agent = "---\nname: demo-agent\ndescription: Demo agent\nmodel: opus\neffort: high\n---\n\nDo the work. 🔍\n"
    command = (
        "---\ndescription: Demo command\nargument-hint: ignored\n---\n\nDo the command.\n\nPreserve “smart quotes”.\n"
    )

    write_file(tmp_path / ".claude/skills/demo-skill/SKILL.md", skill)
    write_file(tmp_path / ".claude/skills/demo-skill/reference.md", "Reference with café text.\n")
    write_file(tmp_path / ".claude/agents/README.md", "Maintainer notes without frontmatter.\n")
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
    parsed_agent = tomllib.loads(agent)
    assert agent.startswith('name = "demo-agent"\n')
    assert 'description = "Demo agent"' in agent
    assert parsed_agent["model"] == "gpt-5.6-sol"
    assert parsed_agent["model_reasoning_effort"] == "high"
    assert "Do the work. 🔍" in parsed_agent["developer_instructions"]
    assert not (root / ".codex/agents/README.toml").exists()
    assert "● TIGHT dependency." in read_file(root / ".agents/skills/demo-skill/SKILL.md")
    assert "Preserve “smart quotes”." in read_file(root / ".agents/skills/demo-command/SKILL.md")


def test_render_agent_maps_models(tmp_path: Path) -> None:
    source = tmp_path / "agent.md"
    cases = (
        ("fable", "medium", 'model = "gpt-5.6-sol"', 'model_reasoning_effort = "medium"'),
        ("sonnet", "low", 'model = "gpt-5.6-terra"', 'model_reasoning_effort = "low"'),
    )
    for model, effort, expected_model, expected_effort in cases:
        write_file(
            source,
            f"---\nname: demo\ndescription: Demo\nmodel: {model}\neffort: {effort}\n---\nInstructions.\n",
        )
        rendered = sync_claude_assets.render_agent(source)
        assert expected_model in rendered
        assert expected_effort in rendered


@pytest.mark.parametrize(("key", "value"), (("model", "unknown"), ("effort", "extreme")))
def test_render_agent_rejects_unmapped_routing_metadata(tmp_path: Path, key: str, value: str) -> None:
    source = tmp_path / "agent.md"
    write_file(source, f"---\nname: demo\ndescription: Demo\n{key}: {value}\n---\nInstructions.\n")

    with pytest.raises(ValueError, match=rf"unsupported agent {key} {value!r}"):
        sync_claude_assets.render_agent(source)


@pytest.mark.parametrize("missing_key", ("model", "effort"))
def test_render_agent_requires_routing_metadata(tmp_path: Path, missing_key: str) -> None:
    metadata = {"model": "opus", "effort": "high"}
    del metadata[missing_key]
    source = tmp_path / "agent.md"
    routing = "".join(f"{key}: {value}\n" for key, value in metadata.items())
    write_file(source, f"---\nname: demo\ndescription: Demo\n{routing}---\nInstructions.\n")

    with pytest.raises(ValueError, match=rf"frontmatter is missing '{missing_key}'"):
        sync_claude_assets.render_agent(source)


def test_generated_metadata_preserves_readable_unicode(tmp_path: Path) -> None:
    skill = tmp_path / "SKILL.md"
    write_file(skill, "---\nname: demo\ndescription: pflow — readable\n---\nBody.\n")
    agent = tmp_path / "agent.md"
    write_file(
        agent,
        "---\nname: demo\ndescription: pflow — readable\nmodel: opus\neffort: high\n---\nInstructions.\n",
    )

    rendered_skill = sync_claude_assets.render_skill(skill)
    rendered_agent = sync_claude_assets.render_agent(agent)

    assert "pflow — readable" in rendered_skill
    assert "pflow — readable" in rendered_agent
    assert r"\u2014" not in rendered_skill
    assert r"\u2014" not in rendered_agent


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
            "Task ID: **$ARGUMENTS**\nInputs: $ARGUMENTS\ntask_description='$ARGUMENTS'\n"
            "!`git branch --show-current`\n@agent-demo\n{{task_id}}",
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
    assert "Task ID: derive it from the user's request." in rendered
    assert "task_description='THE TASK DESCRIPTION'" in rendered
    assert "Run this command before proceeding:\n\n```bash\ngit branch --show-current\n```" in rendered
    assert "demo\n<task_id>" in rendered


def test_sweeps_generated_skill_dir_with_no_claude_source(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    sync_claude_assets.synchronize(root, write=True)
    orphan_dir = root / ".agents/skills/orphan-skill"
    orphan = orphan_dir / "SKILL.md"
    nested = orphan_dir / "refs/note.md"  # exercises the reverse-sorted rmdir (deepest-first) branch
    write_file(orphan, "---\nname: orphan-skill\ndescription: Orphaned\n---\nstale mirror\n")
    write_file(nested, "stale ref\n")

    check = sync_claude_assets.synchronize(root, write=False)
    assert check.changed == []
    assert check.errors == ["Generated skill has no Claude source: " + str(orphan_dir)]

    result = sync_claude_assets.synchronize(root, write=True)
    assert result.errors == []
    assert orphan in result.changed
    assert nested in result.changed
    assert not orphan_dir.exists()


def test_sweep_preserves_hand_authored_codex_only_skill(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    sync_claude_assets.synchronize(root, write=True)
    # A Codex-only skill has no Claude source by design; it must survive the sweep.
    codex_only = next(iter(sync_claude_assets.CODEX_ONLY_SKILLS))
    kept = root / ".agents/skills" / codex_only / "SKILL.md"
    write_file(kept, "---\nname: " + codex_only + "\ndescription: Codex-only\n---\nhand authored\n")

    check = sync_claude_assets.synchronize(root, write=False)
    assert check.errors == []

    result = sync_claude_assets.synchronize(root, write=True)
    assert result.errors == []
    assert kept.exists()


def test_sweeps_generated_agent_with_no_claude_source(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    sync_claude_assets.synchronize(root, write=True)
    orphan = root / ".codex/agents/orphan-agent.toml"
    write_file(orphan, 'name = "orphan-agent"\n')

    check = sync_claude_assets.synchronize(root, write=False)
    assert check.errors == ["Generated agent has no Claude source: " + str(orphan)]

    result = sync_claude_assets.synchronize(root, write=True)
    assert result.errors == []
    assert not orphan.exists()


def test_cli_reports_invalid_source_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_synchronization(_root: Path, write: bool) -> sync_claude_assets.SyncResult:
        del write
        raise ValueError("invalid source")

    monkeypatch.setattr(sync_claude_assets, "parse_args", lambda: sync_claude_assets.argparse.Namespace(write=False))
    monkeypatch.setattr(sync_claude_assets, "synchronize", fail_synchronization)

    assert sync_claude_assets.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Claude/Codex asset synchronization failed:\ninvalid source\n"


def test_rejects_skill_command_name_collision(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    write_file(
        root / ".claude/skills/demo-command/SKILL.md",
        "---\nname: demo-command\ndescription: Conflicting skill\n---\n",
    )

    result = sync_claude_assets.synchronize(root, write=True)

    assert result.changed == []
    assert result.errors == ["Claude skill and command share generated Codex skill name: demo-command"]
