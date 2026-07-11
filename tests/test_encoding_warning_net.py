"""Canary for the EncodingWarning regression net (Task 116).

The net is a chain with an inert-by-default failure mode: the pyproject
`filterwarnings = ["error::EncodingWarning", ...]` entry promotes
encoding-less IO anywhere in the repo to test failures, but Python only
EMITS EncodingWarning when the interpreter starts with
PYTHONWARNDEFAULTENCODING=1 / -X warn_default_encoding (PEP 597). Delete the
env var from the Makefile or tox, or "simplify" the filter line, and the net
dies silently while everything stays green. These tests make that death loud.

Skip behavior is part of the design: on a bare local `pytest` run (no env
var) the canary SKIPS visibly instead of pretending the net is up. Make
targets fail earlier in their explicit preflight, tox sets the variable, and
CI fails closed below if the setting is ever lost.

Why exec with a faked __name__: warning attribution follows the __name__ of
the frame that calls open() (verified in the Task 116 progress log, Bug 4),
and the filter's module pattern matches against it. Faking it lets the canary
impersonate pflow source without planting a deliberate encoding bug in
src/pflow (which ruff PLW1514 would rightly reject).
"""

import os
import sys

import pytest

encoding_warning_inactive = pytest.mark.skipif(
    not sys.flags.warn_default_encoding,
    reason="EncodingWarning net inactive in this run: PYTHONWARNDEFAULTENCODING=1 not set "
    "(Make targets and tox set it; the canary only certifies runs that claim the net)",
)


def test_encoding_warning_net_is_active_in_ci():
    """Fail closed in CI while allowing an explicit skip for bare local pytest."""
    if sys.flags.warn_default_encoding:
        return
    if os.getenv("CI"):
        pytest.fail("EncodingWarning net is inactive in CI: PYTHONWARNDEFAULTENCODING=1 was not inherited")
    pytest.skip("EncodingWarning net is only required through Make, tox, or CI")


def _open_without_encoding_as(module_name: str, path: object) -> None:
    """Run an encoding-less open() in a frame attributed to `module_name`."""
    code = compile("open(path).close()", f"<canary impersonating {module_name}>", "exec")
    exec(code, {"__name__": module_name, "path": str(path)})  # noqa: S102


@encoding_warning_inactive
def test_encoding_regression_in_pflow_source_fails_loudly(tmp_path):
    """An encoding-less open() attributed to a pflow.* module must be a hard
    error, not a warning. Red here means the net is dead: the env var was
    dropped from the Makefile/CI, or the filterwarnings entry was removed."""
    target = tmp_path / "data.txt"
    target.write_text("x", encoding="utf-8")

    with pytest.raises(EncodingWarning):
        _open_without_encoding_as("pflow._encoding_net_canary", target)


@encoding_warning_inactive
def test_net_covers_test_code_too(tmp_path):
    """An encoding-less open() attributed to a test module must also be a hard
    error. The net was widened from `pflow.*` to a blanket filter once every
    test call site carried an explicit encoding — red here means the filter
    was narrowed back and the test suite can silently regrow encoding-less IO
    that ruff PLW1514 cannot see (fdopen, untyped fixture-derived paths)."""
    target = tmp_path / "data.txt"
    target.write_text("x", encoding="utf-8")

    with pytest.raises(EncodingWarning):
        _open_without_encoding_as("tests._encoding_net_canary", target)


@encoding_warning_inactive
def test_third_party_litellm_stays_ignored(tmp_path):
    """litellm's own encoding-less opens are not pflow's bug to fail on.
    Red here means the `ignore::EncodingWarning:litellm.*` entry was dropped —
    the blanket error filter would then detonate on litellm import-time IO
    (json_loader.py, endpoint_factory.py) in tests that touch LLM paths."""
    target = tmp_path / "data.txt"
    target.write_text("x", encoding="utf-8")

    # Must not raise and must not surface as a warning — the ignore filter
    # swallows it entirely.
    _open_without_encoding_as("litellm._encoding_net_canary", target)
