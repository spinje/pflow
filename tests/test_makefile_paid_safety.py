"""Contract pins for Make targets that promise not to make paid calls."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _target_recipe(makefile: str, target: str) -> str:
    marker = f"\n{target}:"
    start = makefile.rindex(marker) + 1
    remainder = makefile[start:]
    end = remainder.find("\n\n")
    return remainder if end == -1 else remainder[:end]


def test_every_safe_test_target_excludes_paid_marker() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")

    for target in ("test", "test-e2e", "test-debug", "test-all-local", "test-with-skipped"):
        recipe = _target_recipe(makefile, target)
        assert "not paid" in recipe, f"make {target} can collect paid provider tests"


def test_paid_codex_smoke_has_explicit_marker() -> None:
    source = (REPO_ROOT / "tests/test_nodes/test_agent/test_codex_backend.py").read_text(encoding="utf-8")
    marker = "@pytest.mark.paid\n@pytest.mark.skipif"

    assert marker in source
