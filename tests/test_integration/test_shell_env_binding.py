"""``env:`` is a working channel — through the validator, the compiler and the run (Task 118 Part 1).

Before this task any non-string ``env:`` value passed ``--validate-only`` and then
crashed at spawn as a false "exit code -2"; a JSON-looking string was parsed and
re-serialized on the way in; an unreadable name reached the child silently. Each
class below drives the real ``WorkflowRunner`` (or ``compile_workflow`` for the
compiler's twin check) and asserts what the command actually received. The
binding rule itself is unit-tested in ``tests/test_nodes/test_shell/test_env_binding.py``.
"""

from __future__ import annotations

import copy
import os
import sys
from itertools import pairwise
from pathlib import Path
from typing import Any, ClassVar

import pytest

from pflow.core.diagnostic import Diagnostic
from pflow.core.exceptions import CompilationError
from pflow.core.workflow.status import WorkflowStatus
from pflow.execution.result import ExecutionResult, RunnerConfig
from pflow.execution.runner import WorkflowRunner
from pflow.nodes.shell import shell as shell_module
from pflow.nodes.shell.shell import ShellNode
from pflow.registry import Registry
from pflow.runtime import WorkflowEngine, compile_workflow

PRINT_V = 'printf "%s" "$V"'


def _shell(env: Any, command: str = PRINT_V, node_id: str = "s", **extra: Any) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": "shell",
        "purpose": "Print the bound value.",
        "params": {"command": command, "env": env},
        **extra,
    }


def _ir(*nodes: dict[str, Any], inputs: dict[str, Any] | None = None) -> dict[str, Any]:
    ir: dict[str, Any] = {
        "ir_version": "0.1.0",
        "nodes": list(nodes),
        "edges": [{"from": a["id"], "to": b["id"]} for a, b in pairwise(nodes)],
    }
    if inputs:
        ir["inputs"] = inputs
    return ir


def _input(type_: str, **spec: Any) -> dict[str, Any]:
    return {"type": type_, "required": False, "description": "A value.", **spec}


def _code(node_id: str, value: Any) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": "code",
        "purpose": "Produce a typed value.",
        "params": {"code": f"result: Any = {value!r}"},
    }


def _run(ir: dict[str, Any], params: dict[str, Any] | None = None) -> ExecutionResult:
    return WorkflowRunner().run(ir, dict(params or {}), RunnerConfig())


def _validate(workflow: dict[str, Any] | str) -> tuple[list[Diagnostic], list[Diagnostic]]:
    result = WorkflowRunner().validate(workflow, {})
    return list(result.errors), list(result.warnings)


def _stdout(result: ExecutionResult, node_id: str = "s") -> str:
    assert result.success, [d.message for d in result.errors]
    return str(result.shared_after[node_id]["stdout"])


# (value, input type, the text the command receives) — `core/templates.to_string`.
VALUE_TEXT: tuple[tuple[Any, str, str], ...] = (
    (3, "number", "3"),
    (3.0, "number", "3.0"),
    (True, "boolean", "True"),
    ({"a": 1, "b": [1, 2]}, "object", '{"a": 1, "b": [1, 2]}'),
    ([], "array", "[]"),
    ("x", "string", "x"),
)


# Prints the value, then how many `V=` entries the environment holds — so an empty text is
# told apart from a variable that was never bound.
PROBE_V = 'printf "%s|" "$V"; env | grep -c "^V="'


class TestEveryValueBinds:
    """Scenario 1 — validation passes, then the run crashes. Now: valid AND the command prints the text."""

    @pytest.mark.parametrize(("value", "text"), [(v, t) for v, _, t in VALUE_TEXT] + [(None, "")])
    def test_a_literal_value(self, value: Any, text: str) -> None:
        ir = _ir(_shell({"V": value}, PROBE_V))
        assert _validate(ir)[0] == []
        assert _stdout(_run(ir)) == f"{text}|1"

    @pytest.mark.parametrize(("value", "type_", "text"), VALUE_TEXT)
    def test_a_workflow_input(self, value: Any, type_: str, text: str) -> None:
        ir = _ir(_shell({"V": "${x}"}, PROBE_V), inputs={"x": _input(type_)})
        assert _validate(ir)[0] == []
        assert _stdout(_run(ir, {"x": value})) == f"{text}|1"

    @pytest.mark.parametrize(("value", "text"), [(v, t) for v, _, t in VALUE_TEXT] + [(None, "")])
    def test_an_upstream_output(self, value: Any, text: str) -> None:
        ir = _ir(_code("up", value), _shell({"V": "${up.result}"}, PROBE_V))
        assert _validate(ir)[0] == []
        assert _stdout(_run(ir)) == f"{text}|1"

    def test_an_unset_optional_input(self) -> None:
        ir = _ir(_shell({"V": "${opt}"}, PROBE_V), inputs={"opt": _input("string")})
        assert _validate(ir)[0] == []
        assert _stdout(_run(ir)) == "|1"  # bound, empty — not dropped

    @pytest.mark.parametrize("parallel", [False, True], ids=["sequential", "parallel"])
    def test_the_batch_index(self, parallel: bool) -> None:
        batch = {"items": ["a", "b", "c"], "as": "item", "parallel": parallel}
        ir = _ir(_shell({"V": "${__index__}", "ITEM": "${item}"}, 'printf "%s-%s" "$V" "$ITEM"', batch=batch))
        assert _validate(ir)[0] == []
        result = _run(ir)
        assert result.success, [d.message for d in result.errors]
        assert [item["stdout"] for item in result.shared_after["s"]["results"]] == ["0-a", "1-b", "2-c"]

    def test_a_parallel_batch_leaves_the_process_and_the_compiled_config_untouched(self) -> None:
        batch = {"items": ["a", "b", "c", "d"], "as": "item", "parallel": True}
        ir = _ir(_shell({"V": "${__index__}", "N": 3}, 'printf "%s:%s" "$V" "$N"', batch=batch))
        compiled = compile_workflow(ir, Registry())
        config = compiled.node_configs["s"].template_config
        assert config is not None
        before_env = dict(os.environ)
        before_params = copy.deepcopy(config.template_params)
        store: dict[str, Any] = {**compiled.resolved_defaults}
        WorkflowEngine().run(compiled, store)
        assert [item["stdout"] for item in store["s"]["results"]] == ["0:3", "1:3", "2:3", "3:3"]
        assert dict(os.environ) == before_env
        assert config.template_params == before_params
        assert "V" not in os.environ


class TestJsonLookingTextStaysText:
    """Scenario 2 — a JSON-looking string bound directly arrives byte-for-byte (the engine edit).

    Mutation recorded in the progress log: restore ``auto_parse=isinstance(template, (dict, list))``
    in ``resolve_templates`` and the direct rows go red (``{"a": 1}``).
    """

    UPSTREAM: ClassVar[dict[str, Any]] = {
        "id": "up",
        "type": "shell",
        "purpose": "Print compact JSON.",
        "params": {"command": "printf '%s' '{\"a\":1}'"},
    }

    def test_bound_directly_from_upstream(self) -> None:
        ir = _ir(self.UPSTREAM, _shell({"DATA": "${up.stdout}"}, 'printf "%s" "$DATA"'))
        assert _stdout(_run(ir)) == '{"a":1}'

    def test_bound_directly_as_a_batch_item(self) -> None:
        batch = {"items": ['{"a":1}', "[1,2]"], "as": "item"}
        ir = _ir(_shell({"DATA": "${item}"}, 'printf "%s" "$DATA"', batch=batch))
        result = _run(ir)
        assert result.success, [d.message for d in result.errors]
        assert [item["stdout"] for item in result.shared_after["s"]["results"]] == ['{"a":1}', "[1,2]"]

    def test_routed_through_inputs_is_parsed_there_unchanged_from_today(self) -> None:
        """The accepted limit (#686, Task 120's): ``inputs:`` auto-parses, ``env:`` re-serializes."""
        step = _shell({"RAW": "${raw}"}, 'printf "%s" "$RAW"')
        step["params"]["inputs"] = {"raw": "${up.stdout}"}
        assert _stdout(_run(_ir(self.UPSTREAM, step))) == '{"a": 1}'

    def test_a_carried_loop_value_is_parsed_like_inputs(self, tmp_path: Path) -> None:
        """Round 2 reads the CARRIED text (compact ``{"b":2}``, unlike the seed), parsed and re-serialized.

        Fails if the carry is bypassed (round 2 would see the seed again) or if carried text
        stopped being parsed (round 2 would see ``{"b":2}``).
        """
        log = tmp_path / "rounds.txt"
        flag = _code("flag", True)
        step = _shell({"STATE": "${state}", "LOG": str(log)}, """printf '%s|' "$STATE" >> "$LOG"; printf '{"b":2}'""")
        step["params"]["inputs"] = {"state": "${up.stdout}"}
        step["loop"] = {"carry": {"state": "${s.stdout}"}, "while": "${flag.result}", "max_iterations": 2}
        result = _run(_ir(self.UPSTREAM, flag, step))
        assert _stdout(result) == '{"b":2}'
        assert log.read_text(encoding="utf-8") == '{"a": 1}|{"b": 2}|'


class TestInjection:
    """Scenario 3 (#59) — regression guard: a hostile value through a workflow input arrives intact."""

    def test_a_hostile_input_value_is_data(self, tmp_path: Path) -> None:
        value = "-e 'it''s' \"q\" $HOME `id` $(touch pwned)\nline2"
        step = _shell({"V": "${x}"})
        step["params"]["cwd"] = str(tmp_path)
        ir = _ir(step, inputs={"x": _input("string")})
        assert _stdout(_run(ir, {"x": value})) == value
        assert not (tmp_path / "pwned").exists()


class TestBindingFailures:
    """Scenario 4 — a binding failure looked like a command failure. Now it fails before spawn."""

    @pytest.fixture
    def attempts(self, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        """Record every real ``prep()`` and ``exec()`` call, in order (spies that delegate, not stubs).

        ``exec()`` is the retried phase and the one that spawns: a binding failure must show
        ``prep`` and no ``exec`` — if binding moved into ``exec()`` the retries would show here.
        """
        calls: list[str] = []
        real_prep, real_exec = ShellNode.prep, ShellNode.exec

        def prep(self: ShellNode, shared: dict[str, Any]) -> dict[str, Any]:
            calls.append("prep")
            return real_prep(self, shared)

        def exec_(self: ShellNode, prep_res: dict[str, Any]) -> dict[str, Any]:
            calls.append("exec")
            return real_exec(self, prep_res)

        monkeypatch.setattr(ShellNode, "prep", prep)
        monkeypatch.setattr(ShellNode, "exec", exec_)
        return calls

    @staticmethod
    def _assert_failed_before_spawn(result: ExecutionResult, expected: str) -> None:
        messages = [d.message for d in result.errors]
        assert not result.success
        assert any(expected in message for message in messages), messages
        assert not any("exit code" in message for message in messages), messages
        # The failure record is the medium a command failure fills (`test_a_command_failure_…`):
        # a binding failure is an exception with no exit code in it.
        failure = result.shared_after["__failures__"]["s"]
        assert failure["category"] == "exception"
        assert "exit_code" not in failure["data"]

    def test_a_command_failure_records_its_exit_code_in_the_same_record(self) -> None:
        """Control for the absence check above: the record does carry an exit code when a command ran."""
        result = _run(_ir(_shell({"V": "x"}, "exit 3")))
        assert not result.success
        failure = result.shared_after["__failures__"]["s"]
        assert (failure["category"], failure["data"]["exit_code"]) == ("shell_failure", 3)

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("a\0b", "The value bound to V in env: contains a NUL byte"),
            pytest.param(
                "cut \ud800",
                "The value bound to V in env: contains a character the operating system cannot",
                marks=pytest.mark.skipif(sys.platform == "win32", reason="UTF-16 environments hold a lone surrogate"),
            ),
        ],
        ids=["nul", "lone-surrogate"],
    )
    def test_an_unbindable_value_under_ignore_errors_and_retry(
        self, value: str, expected: str, attempts: list[str]
    ) -> None:
        step = _shell({"V": "${x}"}, retry={"max": 3})
        step["params"]["ignore_errors"] = True
        ir = _ir(step, inputs={"x": _input("string")})
        assert _validate(ir)[0] == []
        self._assert_failed_before_spawn(_run(ir, {"x": value}), expected)
        assert attempts == ["prep"]

    def test_an_unreadable_name_arriving_whole(self, attempts: list[str]) -> None:
        step = _shell("${cfg}", retry={"max": 3})
        step["params"]["ignore_errors"] = True
        ir = _ir(step, inputs={"cfg": _input("object", default={"bad-name": "x"})})
        assert _validate(ir)[0] == []  # a whole-templated env: is checked when the step runs
        self._assert_failed_before_spawn(_run(ir), "env name 'bad-name' cannot be read as a shell variable.")
        assert attempts == ["prep"]

    def test_a_continue_batch_fails_the_item_once_and_finishes(self, attempts: list[str]) -> None:
        batch = {
            "items": [{"GOOD": "1"}, {"bad-name": "2"}, {"GOOD": "3"}],
            "as": "item",
            "error_handling": "continue",
            "max_retries": 3,
        }
        ir = _ir(_shell("${item}", 'printf "%s" "$GOOD"', batch=batch))
        result = _run(ir)
        assert result.status is WorkflowStatus.DEGRADED
        output = result.shared_after["s"]
        assert [item["stdout"] for item in output["results"]] == ["1", "3"]
        assert [(error["index"], "env name 'bad-name'" in error["error"]) for error in output["errors"]] == [(1, True)]
        # Item 1 is prepared once and never spawned, despite `max_retries: 3`.
        assert attempts == ["prep", "exec", "prep", "prep", "exec"]

    @pytest.mark.skipif(sys.platform == "win32", reason="the Windows size refusal is observed by D8-4 first")
    def test_an_oversized_value_names_itself_and_is_not_retried(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A real OS refusal (1.1 MB: over macOS's total and Linux's per-value limit)."""
        real = shell_module._run_posix_shell_command
        spawns: list[str] = []

        def spy(command: str, **kwargs: Any) -> Any:
            spawns.append(command)
            return real(command, **kwargs)

        monkeypatch.setattr(shell_module, "_run_posix_shell_command", spy)
        step = _shell({"BIG": "${x}"}, 'printf "%s" "$BIG" | wc -c', retry={"max": 3})
        step["params"]["ignore_errors"] = True
        ir = _ir(step, inputs={"x": _input("string")})
        self._assert_failed_before_spawn(_run(ir, {"x": "x" * 1_100_000}), "(largest: BIG 1.1 MB bound in env:")
        assert len(spawns) == 1


def _names_markdown(tmp_path: Path, env_block: str) -> Path:
    path = tmp_path / "names.pflow.md"
    path.write_text(
        "# Names\n\nEnv names.\n\n## Steps\n\n### s\n\nShow.\n\n- type: shell\n"
        f"- env:\n{env_block}\n```shell command\necho hi\n```\n",
        encoding="utf-8",
    )
    return path


class TestNamesAgreeEverywhere:
    """Scenario 5 — validate-only, the compiler and the run say the same about a name."""

    @pytest.mark.parametrize("name", ["my-var", "1x", "a.b", ""])
    def test_validator_compiler_and_run(self, name: str) -> None:
        sentence = f"env name '{name}' cannot be read as a shell variable."
        ir = _ir(_shell({name: "v"}))
        errors, _ = _validate(ir)
        assert [(e.message, e.context["path"]) for e in errors] == [
            (f"Step 's': {sentence}", f"nodes[id=s].params.env.{name}")
        ]
        with pytest.raises(CompilationError) as exc_info:
            compile_workflow(ir, Registry())
        wrapped = exc_info.value.wrapped_diagnostics or []
        assert [(d.message, d.context["path"]) for d in wrapped] == [(e.message, e.context["path"]) for e in errors]
        whole = _ir(_shell("${cfg}"), inputs={"cfg": _input("object", default={name: "v"})})
        failed = _run(whole)
        assert any(d.message.startswith(sentence) for d in failed.errors), [d.message for d in failed.errors]

    @pytest.mark.parametrize(("yaml_key", "written"), [("1", "1"), ("true", "true"), ("null", "null")])
    def test_a_non_text_yaml_key_is_named_as_written(self, tmp_path: Path, yaml_key: str, written: str) -> None:
        errors, _ = _validate(str(_names_markdown(tmp_path, f"    {yaml_key}: v\n")))
        assert [(e.message, e.context["path"]) for e in errors] == [
            (f"Step 's': env name '{written}' cannot be read as a shell variable.", f"nodes[id=s].params.env.{written}")
        ]
        assert errors[0].suggestions == [
            "Use letters, digits and underscores, not starting with a digit — "
            f"e.g. {'VAR_1' if written == '1' else written.upper()} — and read it as "
            f'"${"VAR_1" if written == "1" else written.upper()}" in the command.'
        ]

    def test_a_literal_non_map(self) -> None:
        errors, _ = _validate(_ir(_shell(["A=1"])))
        assert [(e.message, e.context["path"]) for e in errors] == [
            ("Step 's': env must be a map of NAME: value — got a list.", "nodes[id=s].params.env")
        ]

    @pytest.mark.skipif(sys.platform == "win32", reason="UTF-16 environments hold a lone surrogate")
    @pytest.mark.parametrize("value", [{"text": "cut \ud800"}, ["cut \ud800"]], ids=["object", "array"])
    def test_a_literal_container_is_checked_as_the_text_it_binds(self, value: Any) -> None:
        """An object/array binds as JSON text; a string inside it that the OS cannot encode fails at
        validation and compile, not after earlier steps have run."""
        ir = _ir(_shell({"DATA": value}))
        errors, _ = _validate(ir)
        assert [e.context["path"] for e in errors] == ["nodes[id=s].params.env.DATA"]
        assert "The value bound to DATA in env: contains a character the operating system" in errors[0].message
        with pytest.raises(CompilationError):
            compile_workflow(ir, Registry())

    def test_a_literal_nul(self) -> None:
        errors, _ = _validate(_ir(_shell({"DATA": "a\0b"})))
        assert [e.context["path"] for e in errors] == ["nodes[id=s].params.env.DATA"]
        assert errors[0].message.startswith("Step 's': The value bound to DATA in env: contains a NUL byte")


class TestCase:
    """Scenario 6 — names that differ only by case."""

    def test_a_case_duplicate_is_an_error(self) -> None:
        errors, warnings = _validate(_ir(_shell({"Path": "a", "PATH": "b"})))
        assert [(e.message, e.suggestions, e.context["path"]) for e in errors] == [
            (
                "Step 's': env names 'Path' and 'PATH' differ only by case — on Windows they are one variable.",
                ["Keep one of them."],
                "nodes[id=s].params.env",
            )
        ]
        # The shell-owned warning fires once per name, not once per spelling.
        assert [w.context["path"] for w in warnings] == ["nodes[id=s].params.env.Path"]

    def test_a_lower_case_shell_owned_name_warns_and_runs(self) -> None:
        ir = _ir(_shell({"path": "/x"}, 'printf "%s" "$path"'))
        errors, warnings = _validate(ir)
        assert errors == []
        assert [w.message for w in warnings] == [
            "Step 's' sets path in env:, which on Windows is PATH (names ignore case there), replacing the PATH "
            "the command inherits — commands outside the new value will not be found."
        ]
        if sys.platform != "win32":  # on Windows `path` IS the PATH — the warning's point
            assert _stdout(_run(ir)) == "/x"


class TestWarningsDoNotRefuse:
    """Scenario 7 — the clobber and YAML-boolean warnings never stop a workflow."""

    def test_setting_path_warns_with_the_ruled_text(self) -> None:
        errors, warnings = _validate(_ir(_shell({"PATH": "/opt/bin"})))
        assert errors == []
        assert [(w.message, w.suggestions, w.context["path"]) for w in warnings] == [
            (
                "Step 's' sets PATH in env:, replacing the PATH the command inherits — commands outside the new "
                "value will not be found.",
                [
                    'To add a directory, leave PATH out of env: and extend it in the command: export PATH="/opt/bin:$PATH" '
                    "(env: values are not shell-expanded). To pass data, use another name — e.g. TOOL_PATH."
                ],
                "nodes[id=s].params.env.PATH",
            )
        ]

    @pytest.mark.parametrize(
        ("name", "consequence"),
        [
            ("HOME", "it decides `~` and where tools look for their config files"),
            ("IFS", "it decides how the shell splits words"),
            ("BASH_ENV", "it names a file the shell runs before the command"),
            ("LD_PRELOAD", "it names a library loaded into every program the command starts"),
        ],
    )
    def test_each_shell_owned_name_states_its_consequence(self, name: str, consequence: str) -> None:
        _, warnings = _validate(_ir(_shell({name: "v"})))
        assert [(w.message, w.suggestions) for w in warnings] == [
            (
                f"Step 's' sets {name} in env:, replacing the {name} the command inherits — {consequence}.",
                [f"To pass data, use another name — e.g. TOOL_{name}."],
            )
        ]

    def test_a_literal_yaml_boolean_warns_and_binds_as_python_text(self) -> None:
        ir = _ir(_shell({"DEBUG": True}, 'printf "%s" "$DEBUG"'))
        errors, warnings = _validate(ir)
        assert errors == []
        assert [(w.message, w.suggestions) for w in warnings] == [
            (
                "Step 's': env DEBUG is the YAML boolean true and binds as the text True.",
                ['Quote it ("true") if the command compares text.'],
            )
        ]
        assert _stdout(_run(ir)) == "True"

    def test_a_quoted_or_templated_value_does_not_warn(self) -> None:
        ir = _ir(_code("up", True), _shell({"DEBUG": "true", "FLAG": "${up.result}", "LITERAL": True}))
        errors, warnings = _validate(ir)
        assert errors == []
        # Only the literal boolean warns: the medium shows the warning, and only for LITERAL.
        assert [w.context["path"] for w in warnings] == ["nodes[id=s].params.env.LITERAL"]


class TestRegressionGuards:
    """Scenario 8 — true before this task; kept true."""

    def test_a_changed_env_value_changes_the_memo_key(self, tmp_path: Path) -> None:
        counter = tmp_path / "runs.txt"
        step = _shell({"V": "${v}", "COUNTER": str(counter)}, 'echo run >> "$COUNTER"; printf "%s" "$V"', cache=True)
        ir = _ir(step, inputs={"v": _input("string")})
        assert _stdout(_run(ir, {"v": "one"})) == "one"
        assert _stdout(_run(ir, {"v": "one"})) == "one"
        assert counter.read_text(encoding="utf-8").count("run") == 1  # the second run was a memo hit
        assert _stdout(_run(ir, {"v": "two"})) == "two"
        assert counter.read_text(encoding="utf-8").count("run") == 2
