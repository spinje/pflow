"""``path_state``: a path that cannot be checked is ``unknown``, never ``absent`` (Python 3.14's ``exists()``
reads a permission fault as "no file")."""

from __future__ import annotations

import errno
import os
import sys
from pathlib import Path
from typing import Any

import pytest

from pflow.core.path_state import path_state


def test_present_absent_and_a_file_in_the_path(tmp_path: Path) -> None:
    present = tmp_path / "wf.pflow.md"
    present.write_text("# wf\n", encoding="utf-8")

    assert path_state(present) == "present"
    assert path_state(str(tmp_path / "gone.pflow.md")) == "absent"
    assert path_state(str(present / "child")) == "absent"  # NotADirectoryError: nothing can be there


def test_a_stat_fault_is_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    present = tmp_path / "wf.pflow.md"
    present.write_text("# wf\n", encoding="utf-8")

    def denied(_path: Any, *args: Any, **kwargs: Any) -> os.stat_result:
        raise PermissionError(errno.EACCES, "denied")

    monkeypatch.setattr(os, "stat", denied)
    assert path_state(present) == "unknown"


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_a_link_whose_target_is_unavailable_is_unknown_not_absent(tmp_path: Path) -> None:
    """An unmounted volume or a moved target: the entry is there, so it was not deleted."""
    link = tmp_path / "wf.pflow.md"
    link.symlink_to(tmp_path / "unmounted" / "wf.pflow.md")

    assert path_state(link) == "unknown"
