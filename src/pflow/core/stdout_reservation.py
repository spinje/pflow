"""Reserve the process's stdout for machine output while pflow runs other code.

pflow's stdout carries data another program reads: the MCP server's JSON-RPC
stream, a run's result or ``--output-format json`` document. Code pflow runs
in-process can write to it too — a thread a code node starts, a library's
``print``, a subprocess that inherits stdout — and any such write corrupts that
data. Inside :func:`reserve_stdout` file descriptor 1 points at stderr, so all
of those land on stderr, and the real stdout is reachable only through the
yielded stream.

The redirect is at the descriptor level because inherited subprocess stdout and
C-level writes never pass through ``sys.stdout``. The ``sys.stdout`` object is
left in place (it now writes to stderr through fd 1), so the code node's
per-execution capture router (``nodes/python/output_capture.py``) composes
without change.
"""

import contextlib
import os
import sys
from collections.abc import Iterator
from typing import BinaryIO


@contextlib.contextmanager
def reserve_stdout() -> Iterator[BinaryIO]:
    """Point fd 1 at stderr for the block; yield a binary stream on the real stdout.

    On exit, text still buffered in ``sys.stdout`` is flushed (to stderr) before
    the real stdout is put back on fd 1, so buffered stray writes cannot reach it.
    """
    if sys.stdout is None:  # started with stdout closed (`>&-`): no reader to protect
        with open(os.devnull, "wb") as nowhere:
            yield nowhere
        return
    sys.stdout.flush()
    reserved = os.fdopen(os.dup(1), "wb")
    try:
        os.dup2(2, 1)
        yield reserved
    finally:
        try:
            sys.stdout.flush()
        finally:
            os.dup2(reserved.fileno(), 1)
            reserved.close()
