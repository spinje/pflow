"""Agent instruction files must reference paths that exist.

Stale path references make a review agent confidently wrong (2026-06 audit:
a dead `.taskmaster/knowledge/decision-deep-dives/` pointer and a renamed
batch module survived in agent files long after the code moved). This test
mechanically pins every backtick-quoted file reference in `.claude/agents/`
to a real path. It cannot catch stale *structural claims* (step counts,
mechanisms) — those need a periodic audit.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENTS_DIR = REPO_ROOT / ".claude" / "agents"

# Backtick-quoted tokens ending in a known file extension. Requires a "/" so
# bare-filename shorthand (`engine.py`) and example names (`item-0.md`) are
# skipped — only path-shaped references are unambiguous enough to pin.
_PATH_RE = re.compile(r"`([A-Za-z_.][\w.-]*/[\w./-]*\.(?:py|md|toml|json|yaml|yml|cfg))`")

# Tokens with template placeholders are examples, not references.
_PLACEHOLDER_RE = re.compile(r"[{*<>]|task_N|test_X|test_Y|_N\b|\bX\b|\bY\b")

# Deliberate historical citations ("then X, now Y"). Each entry must still be
# cited by some agent file — the companion test below fails when one goes
# stale, so the allowlist can't accumulate dead weight.
HISTORICAL_ALLOWLIST = {
    "runtime/wrappers/batch_node.py",  # pre-wrapper-removal architecture, cited as history
}


def _resolves(token: str) -> bool:
    candidates = [
        REPO_ROOT / token,
        REPO_ROOT / "src" / "pflow" / token,
        REPO_ROOT / "tests" / token,
    ]
    if any(c.exists() for c in candidates):
        return True
    # Fragments relative to a per-task dir, e.g. `implementation/progress-log.md`.
    return any((REPO_ROOT / ".taskmaster" / "tasks").glob(f"*/{token}"))


def _iter_agent_tokens():
    for agent_file in sorted(AGENTS_DIR.glob("*.md")):
        for token in sorted(set(_PATH_RE.findall(agent_file.read_text()))):
            yield agent_file.name, token


def test_agent_file_references_resolve():
    missing = [
        f"{name}: `{token}`"
        for name, token in _iter_agent_tokens()
        if not _PLACEHOLDER_RE.search(token) and token not in HISTORICAL_ALLOWLIST and not _resolves(token)
    ]
    assert not missing, (
        "Agent files reference paths that don't exist. Update the agent file, or add the "
        "path to HISTORICAL_ALLOWLIST if it's a deliberate historical citation:\n" + "\n".join(missing)
    )


def test_agent_reference_scan_is_meaningful():
    """Guard against the extractor silently matching nothing."""
    tokens = list(_iter_agent_tokens())
    assert len(tokens) >= 50, f"Expected 50+ path references across agent files, found {len(tokens)}"


def test_historical_allowlist_entries_still_cited():
    cited = {token for _, token in _iter_agent_tokens()}
    stale = HISTORICAL_ALLOWLIST - cited
    assert not stale, f"Allowlist entries no longer cited by any agent file — remove them: {sorted(stale)}"
