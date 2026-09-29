"""Reserve the process's stdio for machine traffic while pflow runs other code.

pflow's stdout carries data another program reads: the MCP server's JSON-RPC
stream, a run's result or ``--output-format json`` document. Code pflow runs
in-process can write to it too — a thread a code node starts, a library's
``print``, a subprocess that inherits stdout — and any such write corrupts that
data. Inside :func:`reserve_stdout` file descriptor 1 points at stderr, so all
of those land on stderr, and the real stdout is reachable only through the
yielded stream.

Under ``pflow mcp serve`` stdin is the JSON-RPC input stream, and the same code
can read it: ``input()`` in a code node, a subprocess that inherits stdin. Such
a read eats protocol bytes or blocks until the next message arrives. Inside
:func:`reserve_stdin` fd 0 points at the null device, so those reads see EOF,
and the real stdin is reachable only through the yielded stream.

The redirects are at the descriptor level because inherited subprocess stdio and
C-level reads/writes never pass through ``sys.stdin``/``sys.stdout``. Those
objects are left in place (they now use the redirected descriptors), so the code
node's per-execution capture router (``nodes/python/output_capture.py``)
composes without change.
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


@contextlib.contextmanager
def reserve_stdin() -> Iterator[BinaryIO]:
    """Point fd 0 at the null device for the block; yield a binary stream on the real stdin."""
    if sys.stdin is None:  # started with stdin closed (`<&-`): no input to protect
        with open(os.devnull, "rb") as nothing:
            yield nothing
        return
    reserved = os.fdopen(os.dup(0), "rb")
    try:
        null_fd = os.open(os.devnull, os.O_RDONLY)
        try:
            os.dup2(null_fd, 0)
        finally:
            os.close(null_fd)
        yield reserved
    finally:
        os.dup2(reserved.fileno(), 0)
        reserved.close()
