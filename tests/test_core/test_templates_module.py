"""Pins for the template language's home, ``pflow.core.templates`` (Task 170)."""

import subprocess

import pytest

import pflow.core.templates as templates
import pflow.runtime.template_resolver as shim


def test_shim_re_exports_the_same_objects() -> None:
    """Tests still import the old path (until the shim is deleted); a copy of the class
    would split monkeypatches (``patch.object(TemplateResolver, ...)``) between two objects."""
    assert shim.TemplateResolver is templates.TemplateResolver
    assert shim.Resolution is templates.Resolution
    assert shim.resolve is templates.resolve


@pytest.mark.e2e
def test_importing_templates_loads_no_runtime_and_no_litellm(
    uv_exe: str,
    prepared_subprocess_env: dict[str, str],
) -> None:
    """``core/`` consumers (validator, graph scope, cache analysis) import the language at
    module level, so it must stay a leaf: no ``pflow.runtime`` package, no litellm.
    Subprocess for a clean ``sys.modules`` (same pattern as ``test_litellm_runtime.py``)."""
    code = (
        "import sys\n"
        "import pflow.core.templates  # noqa: F401\n"
        "leaked = sorted(k for k in sys.modules if k.split('.')[0] == 'litellm' or k.startswith('pflow.runtime'))\n"
        "assert not leaked, f'pflow.core.templates pulled in: {leaked}'\n"
    )
    result = subprocess.run(  # noqa: S603 — fixture-controlled args, mirrors test_litellm_runtime.py
        [uv_exe, "run", "python", "-c", code],
        env=prepared_subprocess_env,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, f"stdout: {result.stdout.decode()}\nstderr: {result.stderr.decode()}"
