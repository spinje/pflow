"""``env:`` as the shell step's binding channel (Task 118 Part 1, ADR-0016).

Node level: the binding rule (``bind_env`` / ``merge_env``), the node lifecycle
around it (prep binds, exec merges, the OS size refusal, ``exec_fallback``), and
the D8 Windows oracle — real spawns that run on every platform. On POSIX the D8
rows are regression guards; their evidence is the ``tests-windows`` leg.
Workflow-level behaviour (validate-only vs run, batch, retry) lives in
``tests/test_integration/test_shell_env_binding.py``.
"""

from __future__ import annotations

import errno
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from pflow.core.exceptions import PflowError
from pflow.nodes.shell import shell as shell_module
from pflow.nodes.shell.env_binding import EnvBindingError, bind_env, merge_env
from pflow.nodes.shell.shell import ShellNode, _prepare_windows_shell_env
from pflow.registry.metadata_extractor import PflowMetadataExtractor


def _run(shared: dict[str, Any], **params: Any) -> str | None:
    node = ShellNode()
    node.set_params(params)
    return node.run(shared)


# ---------------------------------------------------------------------------
# The binding rule
# ---------------------------------------------------------------------------

# (value, the text the command receives) — exactly what `${x}` produces inside a string.
VALUE_TEXT: tuple[tuple[Any, str], ...] = (
    (3, "3"),
    (3.0, "3.0"),
    (True, "True"),
    (False, "False"),
    (None, ""),
    ({"a": 1, "b": [1, 2]}, '{"a": 1, "b": [1, 2]}'),
    ([], "[]"),
    ("x", "x"),
    ('{"a":1}', '{"a":1}'),  # a string is itself — never parsed and re-serialized
)


class TestBindEnv:
    @pytest.mark.parametrize(("value", "text"), VALUE_TEXT)
    def test_each_value_binds_as_its_template_text(self, value: Any, text: str) -> None:
        assert bind_env({"V": value}) == {"V": text}

    def test_no_env_binds_nothing(self) -> None:
        assert bind_env(None) == {}
        assert bind_env({}) == {}

    def test_returns_a_fresh_dict_even_for_an_all_string_map(self) -> None:
        """Regression guard for the write-back trap: the caller's map may be the compiled config's own."""
        env = {"A": "1"}
        bound = bind_env(env)
        assert bound == env
        assert bound is not env
        bound["B"] = "2"
        assert env == {"A": "1"}

    @pytest.mark.parametrize(
        ("name", "written", "suggestion"),
        [
            ("my-var", "my-var", "MY_VAR"),
            ("1x", "1x", "VAR_1X"),
            ("a.b", "a.b", "A_B"),
            ("", "", "VALUE"),
            ("c-i", "c-i", "C_I"),
            (1, "1", "VAR_1"),  # YAML `1:`
        ],
    )
    def test_a_name_sh_cannot_read_is_refused_naming_it(self, name: Any, written: str, suggestion: str) -> None:
        with pytest.raises(EnvBindingError) as exc_info:
            bind_env({name: "v"})
        assert str(exc_info.value) == (
            f"env name '{written}' cannot be read as a shell variable. Use letters, digits and underscores, "
            f'not starting with a digit — e.g. {suggestion} — and read it as "${suggestion}" in the command.'
        )

    @pytest.mark.parametrize(("key", "written", "kind"), [(True, "true", "boolean"), (None, "null", "null")])
    def test_a_yaml_word_key_is_told_to_quote_not_given_a_yaml_word_back(
        self, key: Any, written: str, kind: str
    ) -> None:
        """`NULL:` / `YES:` / `OFF:` parse as null/booleans; suggesting `NULL`/`TRUE` would loop."""
        with pytest.raises(EnvBindingError) as exc_info:
            bind_env({key: "v"})
        assert str(exc_info.value) == (
            f"env name '{written}' cannot be read as a shell variable. "
            f"YAML read this key as a {kind}, not text: quote the key so it stays the name you wrote."
        )

    def test_a_suggested_name_never_lands_on_an_ambient_variable(self) -> None:
        with pytest.raises(EnvBindingError, match=r"e\.g\. BASH_ENV_VALUE — "):
            bind_env({"bash-env": "v"})

    def test_two_names_differing_only_by_case_are_refused(self) -> None:
        with pytest.raises(EnvBindingError) as exc_info:
            bind_env({"Path": "a", "PATH": "b"})
        assert str(exc_info.value) == (
            "env names 'Path' and 'PATH' differ only by case — on Windows they are one variable. Keep one of them."
        )

    @pytest.mark.parametrize(("env", "kind"), [(["A=1"], "a list"), ("A=1", "a str"), (3, "an int")])
    def test_a_non_map_is_refused(self, env: Any, kind: str) -> None:
        with pytest.raises(EnvBindingError) as exc_info:
            bind_env(env)
        assert str(exc_info.value) == f"env must be a map of NAME: value — got {kind}."

    def test_a_nul_byte_is_refused_naming_the_variable(self) -> None:
        with pytest.raises(EnvBindingError) as exc_info:
            bind_env({"DATA": "a\0b"})
        assert str(exc_info.value) == (
            "The value bound to DATA in env: contains a NUL byte, which an environment variable cannot hold. "
            "Pass that value through stdin instead (`- stdin: ${…}`, read it with cat) and remove DATA from env:."
        )

    @pytest.mark.skipif(sys.platform == "win32", reason="Windows environments are UTF-16: a lone surrogate binds")
    def test_text_the_os_cannot_encode_is_refused_naming_the_variable(self) -> None:
        """A lone surrogate — what a JSON escape cut in half decodes to."""
        with pytest.raises(EnvBindingError) as exc_info:
            bind_env({"DATA": "ok \ud800"})
        # Not the stdin advice: stdin's strict UTF-8 encode refuses the same text.
        assert str(exc_info.value) == (
            "The value bound to DATA in env: contains a character the operating system cannot put in an "
            "environment variable. Repair the invalid Unicode in the upstream value before binding DATA — "
            "passing the same text through stdin fails too."
        )

    def test_the_error_renders_as_a_validation_error_on_env(self) -> None:
        """The ruled "Error: Validation Error" title. Retry/batch behaviour is pinned through the
        engine (``test_shell_env_binding.py::TestBindingFailures``), not by attribute."""
        error = EnvBindingError("x")
        assert isinstance(error, PflowError)
        assert error.param == "env"
        assert error.to_diagnostics()[0].title == "Validation Error"


class TestMergeEnv:
    def test_posix_keeps_names_that_differ_by_case(self) -> None:
        inherited = {"PATH": "/bin", "TEMP": "t"}
        bound = {"Path": "X"}
        assert merge_env(inherited, bound, ignore_case=False) == {"PATH": "/bin", "TEMP": "t", "Path": "X"}

    def test_windows_keeps_the_authored_spelling_and_drops_the_inherited_variant(self) -> None:
        inherited = {"PATH": "/bin", "TEMP": "t"}
        bound = {"Path": "X", "Temp": "u"}
        assert merge_env(inherited, bound, ignore_case=True) == {"Path": "X", "Temp": "u"}

    def test_neither_input_is_mutated(self) -> None:
        inherited = {"PATH": "/bin"}
        bound = {"Path": "X"}
        merged = merge_env(inherited, bound, ignore_case=True)
        merged["NEW"] = "1"
        assert inherited == {"PATH": "/bin"}
        assert bound == {"Path": "X"}


class TestWindowsEnvPreparation:
    """``_prepare_windows_shell_env`` finds PATH / MSYS_NO_PATHCONV whatever their spelling."""

    @pytest.fixture
    def git_bash(self, tmp_path: Path) -> tuple[str, list[str]]:
        bash = tmp_path / "Git" / "bin" / "bash.exe"
        usr_bin = tmp_path / "Git" / "usr" / "bin"
        for directory in (bash.parent, usr_bin):
            directory.mkdir(parents=True)
        bash.touch()
        return str(bash), [str(usr_bin), str(bash.parent)]

    def test_a_bound_mixed_case_path_is_extended_not_duplicated(self, git_bash: tuple[str, list[str]]) -> None:
        bash, support = git_bash
        child = _prepare_windows_shell_env(
            merge_env({"PATH": "inherited", "msys_no_pathconv": "0"}, {"Path": "X"}, ignore_case=True), bash
        )
        path_keys = [key for key in child if key.upper() == "PATH"]
        assert path_keys == ["Path"]
        assert child["Path"].split(os.pathsep) == [*support, "X"]
        assert [key for key in child if key.upper() == "MSYS_NO_PATHCONV"] == ["msys_no_pathconv"]
        assert child["msys_no_pathconv"] == "0"

    def test_exec_merges_case_insensitively_on_win32(
        self, monkeypatch: pytest.MonkeyPatch, git_bash: tuple[str, list[str]]
    ) -> None:
        """The win32 exec branch: the env handed to Git Bash has one PATH, the authored one, extended."""
        bash, support = git_bash
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(shell_module, "_resolve_windows_bash", lambda: bash)
        monkeypatch.setenv("PATH", "inherited-entry")
        spawned: dict[str, Any] = {}

        def capture(bash_path: str, command: str, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
            spawned.update(kwargs)
            return subprocess.CompletedProcess([bash_path, "-c", command], 0, b"", b"")

        monkeypatch.setattr(shell_module, "_run_windows_bash_command", capture)
        assert _run({}, command='printf "%s" "$PATH"', env={"Path": "X"}) == "default"
        env = spawned["env"]
        assert [key for key in env if key.upper() == "PATH"] == ["Path"]
        assert env["Path"].split(os.pathsep) == [*support, "X"]
        assert "inherited-entry" not in env["Path"]


# ---------------------------------------------------------------------------
# The node lifecycle around the binding
# ---------------------------------------------------------------------------


class TestShellNodeBinding:
    def test_a_bare_node_binds_non_string_values(self) -> None:
        """The probe path: no engine, no compiler — prep() is where every path binds."""
        shared: dict[str, Any] = {}
        assert _run(shared, command='printf "%s|%s|%s" "$N" "$F" "$Z"', env={"N": 3, "F": True, "Z": None}) == "default"
        assert shared["stdout"] == "3|True|"

    def test_params_env_is_never_written_back(self) -> None:
        env = {"N": 3}
        node = ShellNode()
        node.set_params({"command": 'printf "%s" "$N"', "env": env})
        shared: dict[str, Any] = {}
        node.run(shared)
        assert shared["stdout"] == "3"
        assert node.params["env"] is env
        assert env == {"N": 3}

    @pytest.mark.skipif(sys.platform == "win32", reason="win32 always hands Git Bash a prepared environment")
    def test_a_step_without_env_inherits_the_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Regression guard: no ``env:`` spawns with ``env=None`` (inherit), not a copy."""
        real = shell_module._run_posix_shell_command
        seen: list[Any] = []

        def spy(command: str, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
            seen.append(kwargs["env"])
            return real(command, **kwargs)

        monkeypatch.setattr(shell_module, "_run_posix_shell_command", spy)
        shared: dict[str, Any] = {}
        _run(shared, command="echo hi")
        _run(shared, command="echo hi", env={"A": "1"})
        assert seen[0] is None
        assert seen[1]["A"] == "1"

    def test_a_binding_failure_raises_from_prep_even_under_ignore_errors(self) -> None:
        shared: dict[str, Any] = {}
        with pytest.raises(EnvBindingError, match="env name 'my-var'"):
            _run(shared, command="echo hi", env={"my-var": "x"}, ignore_errors=True)
        assert "exit_code" not in shared

    def test_exec_fallback_reraises_pflow_errors_and_keeps_the_exit_code_contract_for_others(self) -> None:
        node = ShellNode()
        prep_res = {"command": "echo hi"}
        with pytest.raises(EnvBindingError):
            node.exec_fallback(prep_res, EnvBindingError("refused"))
        assert node.exec_fallback(prep_res, OSError("boom"))["exit_code"] == -2

    def test_an_os_size_refusal_is_translated_and_never_retried(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The E2BIG branch on every platform (the real refusal is pinned in D8-4)."""
        calls: list[str] = []

        def refuse(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
            calls.append("spawn")
            raise OSError(errno.E2BIG, "Argument list too long")

        monkeypatch.setattr(shell_module, "_run_posix_shell_command", refuse)
        monkeypatch.setattr(shell_module, "_run_windows_bash_command", refuse)
        node = ShellNode()
        node.max_retries = 3
        node.set_params({
            "command": 'printf "%s" "$BODY"',
            "env": {"BODY": "x" * 3_000, "SMALL": "y"},
            "ignore_errors": True,
        })
        shared: dict[str, Any] = {}
        with pytest.raises(EnvBindingError) as exc_info:
            node.run(shared)
        assert calls == ["spawn"]
        assert "exit_code" not in shared
        message = str(exc_info.value)
        assert message.startswith(
            "The command could not start: its environment and arguments are too large for the operating system "
            "(largest: BODY 3 KB bound in env:, the command 19 bytes). Pass large values through stdin instead"
        )

    def test_the_interface_declares_exactly_the_shell_params(self) -> None:
        """The env comment must not contain ``, NAME: `` — the extractor would register a fake param."""
        metadata = PflowMetadataExtractor().extract_metadata(ShellNode)
        params = metadata["params"]
        assert [param["key"] for param in params] == [
            "stdin",
            "command",
            "cwd",
            "env",
            "timeout",
            "ignore_errors",
            "strip_newline",
        ]
        env = next(param for param in params if param["key"] == "env")
        assert env["type"] == "dict"
        assert "binds as text" in env["description"]


# ---------------------------------------------------------------------------
# D8 — the Windows oracle: real spawns, every platform
# ---------------------------------------------------------------------------


class TestWindowsOracle:
    """Plan D8. Evidence only on ``tests-windows``; the POSIX legs are regression guards.

    A D8-1..3 failure on Windows is checkpoint CP-2 (a design fork: translate values?
    document ``cygpath``?) — never xfail it here.
    """

    def test_d8_1_a_native_path_bound_in_env_is_readable(self, tmp_path: Path) -> None:
        """D8-1: values are data — no path translation; ``cat "$FILE"`` reads a native temp path.

        POSIX leg: regression guard.
        """
        target = tmp_path / "in put.txt"
        target.write_text("pflow-d8-1", encoding="utf-8")
        shared: dict[str, Any] = {}
        assert _run(shared, command='cat "$FILE"', env={"FILE": str(target)}) == "default", shared.get("stderr")
        assert shared["stdout"] == "pflow-d8-1"

    def test_d8_2_a_mixed_case_path_yields_one_path_containing_the_bound_value(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """D8-2: ``env: {Path: X}`` — one PATH-named variable on Windows, holding X, the inherited entry gone.

        POSIX leg: regression guard (names are case-sensitive there: ``Path`` is its own variable).
        """
        inherited = tmp_path / "inherited-sentinel"
        bound = tmp_path / "bound-marker"
        for directory in (inherited, bound):
            directory.mkdir()  # real directories, so no shell layer can drop them as dangling
        monkeypatch.setenv("PATH", os.environ["PATH"] + os.pathsep + str(inherited))
        command = "env | grep -i '^path='"
        # Control: without a PATH binding the sentinel reaches the child — its absence below means something.
        control: dict[str, Any] = {}
        assert _run(control, command=command, env={"PFLOW_D8": "1"}) == "default", control.get("stderr")
        assert "inherited-sentinel" in control["stdout"], control["stdout"]
        shared: dict[str, Any] = {}
        # `env` and `grep` come from Git Bash's support paths — the PATH replacement keeps them.
        assert _run(shared, command=command, env={"Path": str(bound)}) == "default", shared.get("stderr")
        lines = shared["stdout"].splitlines()
        if sys.platform == "win32":
            assert len(lines) == 1, f"expected one PATH-named variable, got {lines}"
            assert "bound-marker" in lines[0]
            assert "inherited-sentinel" not in lines[0]
        else:
            assert sorted(line.split("=", 1)[0] for line in lines) == ["PATH", "Path"]
            assert f"Path={bound}" in lines
            assert next(line for line in lines if line.startswith("PATH=")).endswith(str(inherited))

    def test_d8_2_a_case_colliding_name_keeps_its_spelling_except_windows_path_variables(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """D8-2, second row (CP-2, ruled (a)): a mixed-case name beside an inherited case-variant.

        An ordinary name (``PflowD8`` beside ``PFLOWD8``) is read by its authored spelling, value
        untouched, on every platform. A Windows path variable is the exception, observed on
        ``tests-windows``: Git Bash imports ``Temp`` as ``TEMP`` with the value converted to an
        absolute POSIX path, and ``$Temp`` is empty. POSIX legs: regression guards.
        """

        def child_sees(name: str, value: str) -> tuple[str, list[str]]:
            """``$name`` in the child, and every environment entry spelled like ``name`` in any case."""
            shared: dict[str, Any] = {}
            command = f"printf '%s' \"${name}\"; printf '|'; env | grep -i '^{name}='"
            assert _run(shared, command=command, env={name: value}) == "default", shared.get("stderr")
            read, _, listing = shared["stdout"].partition("|")
            return read, listing.splitlines()

        monkeypatch.setenv("PFLOWD8", "inherited-d8")
        monkeypatch.setenv("TEMP", "inherited-temp")

        # Presence: the general rule holds — the authored spelling reads the bound value.
        read, entries = child_sees("PflowD8", "bound-d8")
        assert read == "bound-d8", entries
        assert "PflowD8=bound-d8" in entries, entries

        read, entries = child_sees("Temp", "bound-temp")
        if sys.platform == "win32":
            assert read == "", entries
            assert len(entries) == 1, entries
            name, _, converted = entries[0].partition("=")
            assert name == "TEMP", entries
            assert converted.startswith("/") and converted.endswith("/bound-temp"), entries
        else:
            assert read == "bound-temp", entries
            assert sorted(entries) == ["TEMP=inherited-temp", "Temp=bound-temp"], entries

    def test_d8_3_a_hostile_value_arrives_byte_identical(self, tmp_path: Path) -> None:
        """D8-3 / #59: quotes, newline, ``$``, backticks, ``$(…)``, a leading ``-`` and non-ASCII, intact.

        The ``$(touch …)`` in the value never runs. POSIX leg: regression guard.
        """
        marker = tmp_path / "pwned"
        value = f"-n 'single' \"double\"\nline2 $HOME `echo tick` $(touch {marker.name}) ünïcødé ✓"
        shared: dict[str, Any] = {}
        assert _run(shared, command='printf "%s" "$V"', env={"V": value}, cwd=str(tmp_path)) == "default", shared.get(
            "stderr"
        )
        assert shared["stdout"] == value
        assert not marker.exists()

    def test_d8_4_a_200kb_value_binds_or_fails_before_spawn(self) -> None:
        """D8-4: a 200 KB value. darwin and win32 bind; linux refuses (one value over 128 KiB).

        Every platform: never "exit code -2", never swallowed by ``ignore_errors``. The win32
        expectation is pinned from ``tests-windows`` (Git Bash bound and read all 200000 bytes).
        """
        value = "x" * 200_000
        node = ShellNode()
        node.set_params({"command": 'printf "%s" "$BIG" | wc -c', "env": {"BIG": value}, "ignore_errors": True})
        shared: dict[str, Any] = {}
        try:
            action = node.run(shared)
        except EnvBindingError as exc:
            outcome = f"refused before spawn: {exc}"
            assert "BIG" in str(exc) and "200 KB" in str(exc), str(exc)
        else:
            outcome = f"bound: action={action} exit_code={shared.get('exit_code')} stdout={shared.get('stdout')!r}"
            assert shared["exit_code"] == 0, f"swallowed or failed after spawn — {outcome}"
            assert shared["stdout"].strip() == "200000", outcome
        assert shared.get("exit_code") != -2, outcome
        if sys.platform == "linux":
            assert outcome.startswith("refused"), outcome
        else:
            assert outcome.startswith("bound"), outcome
