"""Agent instruction files must reference paths, files, and symbols that exist.

Stale references make a review agent confidently wrong (2026-06 audit: a dead
`.taskmaster/knowledge/decision-deep-dives/` pointer, a phantom `BatchExecutor`
class, and a renamed batch module survived in agent files long after the code
moved). Three mechanical checks pin every backtick-quoted reference in
`.claude/agents/`:

1. path-shaped tokens resolve to real files,
2. bare filenames match some file in the repo (ambiguous hits pass — this is a
   freshness guard, not a linker),
3. symbol-shaped tokens (functions, _private names, CamelCase classes) appear
   somewhere in `src/` or `tests/` source.

The symbol check closes the phantom-symbol rot class; it CANNOT catch a
misattributed symbol (a real function credited with the wrong behavior) or a
stale structural claim (step counts, mechanisms) — those still need periodic
audit.
"""

import re
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENTS_DIR = REPO_ROOT / ".claude" / "agents"

# Path-shaped: backtick token with a "/" and a known file extension.
_PATH_RE = re.compile(r"`([A-Za-z_.][\w.-]*/[\w./-]*\.(?:py|md|toml|json|yaml|yml|cfg))`")

# Bare filename: backtick token, no slash, .py/.md only.
_BARE_FILE_RE = re.compile(r"`([A-Za-z_][\w.-]*\.(?:py|md))`")

# Symbol-shaped: `name()` calls, `_private` names, CamelCase (two humps min).
_SYMBOL_RE = re.compile(r"`([A-Za-z_][\w.]*\(\)|_[a-z]\w+|[A-Z][a-z]+(?:[A-Z][a-zA-Z]+)+)`")

# Template placeholders and example names — not real references.
_PLACEHOLDER_RE = re.compile(r"[{*<>]|task_N|test_X|test_Y|_N\b|\bX\b|\bY\b|item-\d+")

# Deliberate historical citations ("then X, now Y") and other intentional
# mentions of things that no longer (or never) exist in the codebase. Each
# entry must still be cited by some agent file — the companion test fails when
# one goes stale, so the allowlists can't accumulate dead weight.
HISTORICAL_PATHS = {
    "runtime/wrappers/batch_node.py",  # pre-wrapper-removal architecture, cited as history
    "batch_node.py",  # same module, cited by bare name in duplication tables
}
ALLOWED_MISSING_SYMBOLS = {
    "BatchExecutor",  # deliberate NEGATIVE mention: "there is no BatchExecutor class"
    "BaseExceptionGroup",  # Python 3.11+ stdlib name in the version-difference table
    "_compute_batch_memo_key",  # historical duplication example (since consolidated)
    "_current_node",  # historical instance-state race example (Task 108, removed)
}


def _resolves(token: str) -> bool:
    # Prefix-guessing across the three common roots is intentionally loose for
    # a freshness guard: a token meant for one root that happens to exist under
    # another still passes. Acceptable — we pin existence, not addressing.
    candidates = [
        REPO_ROOT / token,
        REPO_ROOT / "src" / "pflow" / token,
        REPO_ROOT / "tests" / token,
    ]
    if any(c.exists() for c in candidates):
        return True
    # Fragments relative to a per-task dir, e.g. `implementation/progress-log.md`.
    return any((REPO_ROOT / ".taskmaster" / "tasks").glob(f"*/{token}"))


@lru_cache(maxsize=1)
def _repo_filenames() -> frozenset[str]:
    return frozenset(p.name for p in REPO_ROOT.rglob("*") if p.suffix in (".py", ".md") and ".git" not in p.parts)


@lru_cache(maxsize=1)
def _source_corpus() -> str:
    """All Python source under src/ and tests/, concatenated for substring checks."""
    parts = []
    for root in (REPO_ROOT / "src", REPO_ROOT / "tests"):
        parts.extend(p.read_text(encoding="utf-8", errors="ignore") for p in root.rglob("*.py"))
    return "\n".join(parts)


def _iter_tokens(pattern: re.Pattern[str]):
    for agent_file in sorted(AGENTS_DIR.glob("*.md")):
        for token in sorted(set(pattern.findall(agent_file.read_text(encoding="utf-8")))):
            yield agent_file.name, token


def test_agent_path_references_resolve():
    missing = [
        f"{name}: `{token}`"
        for name, token in _iter_tokens(_PATH_RE)
        if not _PLACEHOLDER_RE.search(token) and token not in HISTORICAL_PATHS and not _resolves(token)
    ]
    assert not missing, (
        "Agent files reference paths that don't exist. Update the agent file, or add the "
        "path to HISTORICAL_PATHS if it's a deliberate historical citation:\n" + "\n".join(missing)
    )


def test_agent_bare_filename_references_resolve():
    names = _repo_filenames()
    missing = [
        f"{name}: `{token}`"
        for name, token in _iter_tokens(_BARE_FILE_RE)
        if "/" not in token
        and not _PLACEHOLDER_RE.search(token)
        and token not in HISTORICAL_PATHS
        and token not in names
    ]
    assert not missing, (
        "Agent files reference filenames that exist nowhere in the repo (renamed/deleted?). "
        "Update the agent file, or add to HISTORICAL_PATHS:\n" + "\n".join(missing)
    )


def test_agent_symbol_references_exist():
    corpus = _source_corpus()
    missing = [
        f"{name}: `{token}`"
        for name, token in _iter_tokens(_SYMBOL_RE)
        if not _PLACEHOLDER_RE.search(token)
        and (base := token.rstrip("()").split(".")[-1]) not in ALLOWED_MISSING_SYMBOLS
        and token.rstrip("()").split(".")[0] not in ALLOWED_MISSING_SYMBOLS
        and base not in corpus
    ]
    assert not missing, (
        "Agent files reference symbols that appear nowhere in src/ or tests/ "
        "(renamed/deleted?). Update the agent file, or add to ALLOWED_MISSING_SYMBOLS "
        "if the mention is deliberate (history, stdlib, negative mention):\n" + "\n".join(missing)
    )


def test_agent_reference_scan_is_meaningful():
    """Guard against the extractors silently matching nothing."""
    paths = list(_iter_tokens(_PATH_RE))
    symbols = list(_iter_tokens(_SYMBOL_RE))
    assert len(paths) >= 50, f"Expected 50+ path references across agent files, found {len(paths)}"
    assert len(symbols) >= 50, f"Expected 50+ symbol references across agent files, found {len(symbols)}"


def test_allowlist_entries_still_cited():
    cited_files = {t for _, t in _iter_tokens(_PATH_RE)} | {t for _, t in _iter_tokens(_BARE_FILE_RE)}
    cited_symbol_bases = {
        part
        for _, t in _iter_tokens(_SYMBOL_RE)
        for part in (t.rstrip("()").split(".")[-1], t.rstrip("()").split(".")[0])
    }
    stale = (HISTORICAL_PATHS - cited_files) | (ALLOWED_MISSING_SYMBOLS - cited_symbol_bases)
    assert not stale, f"Allowlist entries no longer cited by any agent file — remove them: {sorted(stale)}"
