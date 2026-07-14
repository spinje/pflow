"""Prevent removed Claude Code node guidance from returning to current authoring docs."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GUIDANCE_FILES = (
    "src/pflow/guide/core.md",
    "src/pflow/mcp_server/resources/instructions/mcp-agent-instructions.md",
    "src/pflow/mcp_server/resources/instructions/mcp-sandbox-agent-instructions.md",
)


def test_current_agent_guidance_uses_unified_contract() -> None:
    for relative_path in GUIDANCE_FILES:
        text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        assert "Claude Code" not in text, f"stale removed-node guidance in {relative_path}"
        assert "Agent backends require top-level `type: object`" in text
        assert "Claude additionally" in text
