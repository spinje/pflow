"""Packaging invariant: the gitignored web-UI bundle ships in BOTH build targets.

``src/pflow/ui/static/`` (the built ``pflow ui`` frontend, Task 168) is
gitignored, and hatchling honors ``.gitignore`` — so every hatch build target
EXCLUDES it by default. The ``[tool.hatch.build.targets.*].artifacts``
force-include is the only mechanism that ships it.

It must be declared on the **sdist** target as well as the **wheel** target:
``uv build`` and ``make build`` build the wheel FROM the sdist, so a wheel-only
force-include is silently dropped (the sdist never carried the bundle to copy).
The published ``[ui]`` wheel then ships an empty bundle and ``pflow ui`` returns
the 503 "run ``make ui-build``" fallback. This test pins the exact config that
prevents that regression; the release workflow adds a post-build wheel-content
check as the artifact-level guard.
"""

import sys
from pathlib import Path
from typing import Any

import pytest

_PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"
_BUNDLE_PREFIX = "src/pflow/ui/static"


@pytest.fixture(scope="module")
def hatch_targets() -> dict[str, Any]:
    if sys.version_info < (3, 11):
        pytest.skip("tomllib requires Python 3.11+")
    import tomllib

    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    targets: dict[str, Any] = data["tool"]["hatch"]["build"]["targets"]
    return targets


@pytest.mark.parametrize("target", ["sdist", "wheel"])
def test_ui_bundle_force_included_in_build_target(hatch_targets: dict[str, Any], target: str) -> None:
    """Both build targets must force-include the gitignored UI bundle."""
    artifacts = hatch_targets.get(target, {}).get("artifacts", [])
    assert any(_BUNDLE_PREFIX in entry for entry in artifacts), (
        f"[tool.hatch.build.targets.{target}].artifacts must force-include "
        f"{_BUNDLE_PREFIX!r}/** — otherwise hatchling drops the gitignored UI "
        f"bundle from the {target} and `pflow ui` ships empty. See module docstring."
    )
