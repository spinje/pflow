"""Keep NOTICE synchronized with the project's distributable dependencies."""

import json
import re
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib


_ROOT = Path(__file__).resolve().parent.parent
_REQUIREMENT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")


def _normalize_package_name(name: str) -> str:
    """Normalize Python package names according to PEP 503."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _python_requirement_name(requirement: str) -> str:
    match = _REQUIREMENT_NAME.match(requirement)
    assert match is not None, f"Could not parse dependency name from {requirement!r}"
    return _normalize_package_name(match.group())


def _notice_entries(prefix: str) -> list[str]:
    notice = (_ROOT / "NOTICE").read_text(encoding="utf-8")
    return re.findall(rf"^{re.escape(prefix)}: (.+)$", notice, flags=re.MULTILINE)


def test_notice_lists_exactly_the_declared_python_runtime_dependencies() -> None:
    pyproject: dict[str, Any] = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]
    requirements = list(project["dependencies"])
    for optional_requirements in project.get("optional-dependencies", {}).values():
        requirements.extend(optional_requirements)

    expected = {_python_requirement_name(requirement) for requirement in requirements}
    entries = _notice_entries("Python package")
    actual = {_normalize_package_name(entry) for entry in entries}

    assert len(entries) == len(actual), "NOTICE contains duplicate Python package entries"
    assert actual == expected


def test_notice_lists_exactly_the_bundled_web_runtime_dependencies() -> None:
    package_json = json.loads((_ROOT / "web" / "package.json").read_text(encoding="utf-8"))
    expected = set(package_json["dependencies"])
    entries = _notice_entries("Web package")
    actual = set(entries)

    assert len(entries) == len(actual), "NOTICE contains duplicate web package entries"
    assert actual == expected
