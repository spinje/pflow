"""Per-execution stdout/stderr capture for code run on worker threads.

``sys.stdout``/``sys.stderr`` are process-global, so swapping them per
execution breaks as soon as two executions overlap (parallel batch items) or
one outlives its caller (a timed-out execution keeps running): whichever
restore runs last decides what the whole process writes to. Instead, while any
capture is active both streams are replaced by a router that sends each write
to the buffer of the execution context that made it, and every other write to
the stream that was in place before the first capture began.

The route is a ``ContextVar``, so contexts copied from the capturing one
(``asyncio`` tasks, ``asyncio.to_thread``) are captured too. A thread the
captured code starts itself begins with a fresh context, so its writes reach
the original stream.
"""

import contextlib
import contextvars
import io
import sys
import threading
from collections.abc import Iterator
from typing import Any, TextIO, cast

_STDOUT_ROUTE: contextvars.ContextVar[io.StringIO | None] = contextvars.ContextVar("pflow_stdout_route", default=None)
_STDERR_ROUTE: contextvars.ContextVar[io.StringIO | None] = contextvars.ContextVar("pflow_stderr_route", default=None)

_install_lock = threading.Lock()
_active_captures = 0


class _RoutedStream:
    """Stand-in for a process stream: routed contexts hit their buffer, all others ``fallback``."""

    def __init__(self, fallback: TextIO, route: contextvars.ContextVar[io.StringIO | None]) -> None:
        self.fallback = fallback
        self._route = route

    def _target(self) -> TextIO:
        buffer = self._route.get()
        return self.fallback if buffer is None else buffer

    def write(self, text: str) -> int:
        return self._target().write(text)

    def __getattr__(self, name: str) -> Any:
        # flush, isatty, encoding, fileno, getvalue, ... answer for the current target.
        return getattr(self._target(), name)


def _install(stream: TextIO, route: contextvars.ContextVar[io.StringIO | None]) -> TextIO:
    return stream if isinstance(stream, _RoutedStream) else cast(TextIO, _RoutedStream(stream, route))


def _uninstall(stream: TextIO) -> TextIO:
    # Anything that replaced the router while captures were active is left in place.
    return stream.fallback if isinstance(stream, _RoutedStream) else stream


@contextlib.contextmanager
def capture_output() -> Iterator[tuple[io.StringIO, io.StringIO]]:
    """Capture the current context's stdout/stderr writes into fresh buffers.

    Yields ``(stdout_buffer, stderr_buffer)``. The router is removed when the
    last overlapping capture ends, restoring the original stream objects.
    """
    global _active_captures
    stdout_buf, stderr_buf = io.StringIO(), io.StringIO()
    with _install_lock:
        sys.stdout = _install(sys.stdout, _STDOUT_ROUTE)
        sys.stderr = _install(sys.stderr, _STDERR_ROUTE)
        _active_captures += 1
    stdout_token = _STDOUT_ROUTE.set(stdout_buf)
    stderr_token = _STDERR_ROUTE.set(stderr_buf)
    try:
        yield stdout_buf, stderr_buf
    finally:
        _STDOUT_ROUTE.reset(stdout_token)
        _STDERR_ROUTE.reset(stderr_token)
        with _install_lock:
            _active_captures -= 1
            if _active_captures == 0:
                sys.stdout = _uninstall(sys.stdout)
                sys.stderr = _uninstall(sys.stderr)
