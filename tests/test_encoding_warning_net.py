"""Canary for the EncodingWarning regression net (Task 116).

The net is a chain with an inert-by-default failure mode: the pyproject
`filterwarnings = ["error::EncodingWarning:pflow.*"]` entry promotes
encoding-less IO in pflow's own source to test failures, but Python only
EMITS EncodingWarning when the interpreter starts with
PYTHONWARNDEFAULTENCODING=1 / -X warn_default_encoding (PEP 597). Delete the
env var from the Makefile or CI, or "simplify" the filter line, and the net
dies silently while everything stays green. These tests make that death loud.

Skip behavior is part of the design: on a bare `pytest` run (no env var) the
canary SKIPS visibly instead of pretending the net is up — `make test` and
both CI jobs set the env var, so there it must pass.

Why exec with a faked __name__: warning attribution follows the __name__ of
the frame that calls open() (verified in the Task 116 progress log, Bug 4),
and the filter's module pattern matches against it. Faking it lets the canary
impersonate pflow source without planting a deliberate encoding bug in
src/pflow (which ruff PLW1514 would rightly reject).
"""

import sys

import pytest

pytestmark = pytest.mark.skipif(
    not sys.flags.warn_default_encoding,
    reason="EncodingWarning net inactive in this run: PYTHONWARNDEFAULTENCODING=1 not set "
    "(make test and CI set it; the canary only certifies runs that claim the net)",
)


def _open_without_encoding_as(module_name: str, path: object) -> None:
    """Run an encoding-less open() in a frame attributed to `module_name`."""
    code = compile("open(path).close()", f"<canary impersonating {module_name}>", "exec")
    exec(code, {"__name__": module_name, "path": str(path)})  # noqa: S102


def test_encoding_regression_in_pflow_source_fails_loudly(tmp_path):
    """An encoding-less open() attributed to a pflow.* module must be a hard
    error, not a warning. Red here means the net is dead: the env var was
    dropped from the Makefile/CI, or the filterwarnings entry was removed."""
    target = tmp_path / "data.txt"
    target.write_text("x", encoding="utf-8")

    with pytest.raises(EncodingWarning):
        _open_without_encoding_as("pflow._encoding_net_canary", target)


def test_net_stays_scoped_to_pflow_modules(tmp_path):
    """The same call attributed to a non-pflow module must stay an ordinary
    warning. Red here means the filter was widened back to a blanket
    `error::EncodingWarning` — the exact regression documented as Bug 4 in the
    Task 116 progress log (third-party and tmp_path-fixture warnings become
    hundreds of unrelated hard failures)."""
    target = tmp_path / "data.txt"
    target.write_text("x", encoding="utf-8")

    # Must not raise; the emitted warning lands in the pytest summary residue.
    _open_without_encoding_as("tests._encoding_net_canary", target)
