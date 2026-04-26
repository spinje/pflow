"""Pin the lazy-import contract for heavy LLM machinery.

The ~700ms LiteLLM import cost lives behind a deliberate seam — see
``src/pflow/core/llm_client.py``'s module docstring. CLI invocations that
never call the LLM (``pflow validate``, ``--dry-run``, fully-cached runs,
the future ``analyze-cache`` command) skip the cost entirely because
``import litellm`` lives inside ``complete()`` and ``_classify_litellm_error``.

A future refactor that hoists ``import litellm`` to module top, or routes
an engine module through ``llm_client.py``, would silently regress this.
This subprocess test catches the regression — runs ``pflow.cli.main``'s
import chain in a clean interpreter and asserts ``litellm`` did not enter
``sys.modules``.
"""

from __future__ import annotations

import subprocess


def test_litellm_not_imported_by_cli_main(uv_exe, prepared_subprocess_env):
    """Importing the CLI entry point must not pull in litellm.

    The CLI dispatch table reaches every command, so any module the
    CLI loads at import time (engine, runtime, registry, executor)
    cannot import ``llm_client.py`` — that file's top-level
    ``import litellm`` was the original ~700ms drag we removed.
    """
    code = (
        "import sys\n"
        "from pflow.cli.main import main  # noqa: F401\n"
        "litellm_modules = [k for k in sys.modules if k == 'litellm' or k.startswith('litellm.')]\n"
        "assert not litellm_modules, "
        "f'litellm leaked into sys.modules via CLI import: {litellm_modules}'\n"
    )
    result = subprocess.run(  # noqa: S603 — fixture-controlled args, mirrors the established pattern across other subprocess CLI tests
        [uv_exe, "run", "python", "-c", code],
        env=prepared_subprocess_env,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, f"stdout: {result.stdout.decode()}\nstderr: {result.stderr.decode()}"
