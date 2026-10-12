"""Where a `pflow settings set-env` value goes, through the real CLI (#833).

`pflow run` exports settings.env into its own environment at startup (`inject_settings_env_vars`), never over a
name the shell exports, so a shell step sees a stored value without declaring it — and `pflow settings --help`
says so. The exported copy is still a settings value: a declared input it fills is redacted in the saved run
metadata `pflow history` prints. A stored value is also a run's secret value (#801): what the step SEES is read
from the side file it writes, while its printed stdout shows `<REDACTED>`. Real subprocesses: the export is skipped under `PYTEST_CURRENT_TEST`, which the
child must not inherit.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import set_isolated_home

# `STORED_833` is read undeclared by the command; `channel` is a declared input bound through `env:`. Neither
# name is sensitive, so only the settings source can redact `channel`. `SEEN_PATH` is replaced per test by the
# side file the step writes what it saw to.
WORKFLOW = """# Settings probe

Reads a stored value undeclared, and a declared input.

## Inputs

### channel

A channel id.

- type: string
- required: true

## Steps

### show

Print both values.

- type: shell
- env:
    CHAN: ${channel}
    SEEN: "SEEN_PATH"

```shell command
printf 'stored=[%s] chan=[%s]' "$STORED_833" "$CHAN" > "$SEEN"; cat "$SEEN"
```

## Outputs

### out

Shown.

- source: ${show.stdout}
"""


@pytest.mark.e2e
class TestASettingsValueIsExportedAndStillASettingsValue:
    @pytest.fixture
    def cli_env(self, tmp_path: Path, prepared_subprocess_env: dict[str, str]) -> dict[str, str]:
        home = tmp_path / "home"
        (home / ".pflow").mkdir(parents=True)
        registry = Path(prepared_subprocess_env["HOME"]) / ".pflow" / "registry.json"
        (home / ".pflow" / "registry.json").write_text(registry.read_text(encoding="utf-8"), encoding="utf-8")
        env = {
            k: v
            for k, v in prepared_subprocess_env.items()
            if k not in ("PYTEST_CURRENT_TEST", "STORED_833", "channel")
        }
        set_isolated_home(env, home)
        return env

    @staticmethod
    def _pflow(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "pflow.cli", *args], capture_output=True, text=True, encoding="utf-8", env=env
        )
        assert result.returncode == 0, result.stderr
        return result

    def test_an_undeclared_shell_step_sees_a_stored_value_unless_the_shell_exports_the_name(
        self, tmp_path: Path, cli_env: dict[str, str]
    ) -> None:
        seen = tmp_path / "seen.txt"
        workflow = tmp_path / "probe.pflow.md"
        workflow.write_text(WORKFLOW.replace("SEEN_PATH", seen.as_posix()), encoding="utf-8")
        self._pflow(cli_env, "settings", "set-env", "STORED_833", "from-settings")
        self._pflow(cli_env, "settings", "set-env", "channel", "C09")

        printed = self._pflow(cli_env, str(workflow)).stdout
        assert seen.read_text(encoding="utf-8") == "stored=[from-settings] chan=[C09]"
        # A stored value is a secret value: printed, it is scrubbed (C09 is under the 8-character floor).
        assert "stored=[<REDACTED>] chan=[C09]" in printed
        exported = self._pflow({**cli_env, "STORED_833": "from-shell"}, str(workflow))
        assert seen.read_text(encoding="utf-8") == "stored=[from-shell] chan=[C09]"
        assert "stored=[from-shell] chan=[C09]" in exported.stdout

        help_text = " ".join(self._pflow(cli_env, "settings", "--help").stdout.split())
        assert (
            "Stored values are also exported into pflow's environment when a run starts "
            "(never over a variable your shell exports), so shell, code and agent steps see them" in help_text
        )

    def test_a_declared_input_filled_from_settings_is_redacted_in_the_saved_run_history(
        self, tmp_path: Path, cli_env: dict[str, str]
    ) -> None:
        seen = tmp_path / "seen.txt"
        workflow = tmp_path / "probe.pflow.md"
        workflow.write_text(WORKFLOW.replace("SEEN_PATH", seen.as_posix()), encoding="utf-8")
        self._pflow(cli_env, "settings", "set-env", "channel", "C09secret")
        self._pflow(cli_env, "save", str(workflow), "--name", "settings-probe")

        printed = self._pflow(cli_env, "settings-probe").stdout
        assert "chan=[C09secret]" in seen.read_text(encoding="utf-8")
        assert "chan=[<REDACTED>]" in printed
        history = self._pflow(cli_env, "history", "settings-probe").stdout
        assert "channel: <REDACTED>" in history
        assert "C09secret" not in history
