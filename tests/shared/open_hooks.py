"""Intercept file opens in a test — the same way on every supported Python.

A fault or read-set test must catch EVERY open, whichever spelling the code under test uses: ``open(...)``
(``builtins.open``), ``io.open``, or ``Path.open`` / ``read_text`` / ``read_bytes``. Python 3.11+ routes
``Path.open`` through ``io.open`` at call time, but Python 3.10 routes it through
``pathlib._NormalAccessor.open``, bound to ``io.open`` at import — so patching ``builtins``/``io`` alone
misses every pathlib read on 3.10 and the test passes or fails for the wrong reason. ``hook_opens`` patches
all three seams with ONE opener, so each open runs the hook exactly once (``Path.open`` itself is never
patched: on 3.11+ that would count one read twice).

Never patch ``open`` by hand in a test; build on these.
"""

from __future__ import annotations

import builtins
import io
import itertools
import os
import pathlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

# hook(real_open, file, *args, **kwargs) — call ``real_open`` to let the open through.
OpenHook = Callable[..., Any]


def hook_opens(patcher: pytest.MonkeyPatch, hook: OpenHook) -> None:
    """Route every open in the process through ``hook`` until ``patcher`` undoes it."""
    real_open = io.open

    def opener(file: Any, *args: Any, **kwargs: Any) -> Any:
        return hook(real_open, file, *args, **kwargs)

    patcher.setattr(builtins, "open", opener)
    patcher.setattr(io, "open", opener)
    accessor = getattr(pathlib, "_NormalAccessor", None)  # Python 3.10 only
    if accessor is not None:
        patcher.setattr(accessor, "open", staticmethod(opener))


def opened_path(file: Any) -> str | None:
    """The path an ``open`` call names, or ``None`` for a file descriptor."""
    return os.fspath(file) if isinstance(file, (str, os.PathLike)) else None


def record_opens(patcher: pytest.MonkeyPatch) -> list[str]:
    """Every path opened from now on, in order (a file descriptor is not recorded)."""
    opened: list[str] = []

    def record(real_open: Callable[..., Any], file: Any, *args: Any, **kwargs: Any) -> Any:
        path = opened_path(file)
        if path is not None:
            opened.append(path)
        return real_open(file, *args, **kwargs)

    hook_opens(patcher, record)
    return opened


def fault_opens(
    patcher: pytest.MonkeyPatch,
    path: Path | str,
    error: OSError | Callable[[], OSError],
    *,
    nth: int | None = None,
    after: int = 0,
) -> None:
    """Opens of ``path`` raise ``error`` (an instance, or a factory called per fault): only its ``nth`` open
    when given, else every open past the first ``after``. Every other file opens normally."""
    target = os.fspath(path)
    count = itertools.count(1)

    def fault(real_open: Callable[..., Any], file: Any, *args: Any, **kwargs: Any) -> Any:
        if opened_path(file) == target:
            seen = next(count)
            if (seen == nth) if nth is not None else seen > after:
                raise error() if callable(error) else error
        return real_open(file, *args, **kwargs)

    hook_opens(patcher, fault)
