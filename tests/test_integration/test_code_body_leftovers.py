"""A shell command or code block is plain code; old-form references fail loudly (ADR-0016).

The rule (``core/workflow/data_flow.py`` — the body section): a ``${…}`` in a body whose
root is in the step's own scope is a leftover ERROR at ``--validate-only``, at the run and
at compile; a ``$${`` escape is an ERROR; everything else is the language's own text and
runs untouched. Messages are the ruled drafts of the task's diagnostics checkpoint.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest
import yaml
from click.testing import CliRunner, Result

from pflow.cli.main import main
from pflow.core.diagnostic import Diagnostic, Severity
from pflow.core.exceptions import CompilationError
from pflow.core.workflow.data_flow import body_references, step_scope, validate_data_flow
from pflow.core.workflow.validator import WorkflowValidator
from pflow.execution.result import RunnerConfig
from pflow.execution.runner import WorkflowRunner
from pflow.mcp_server.services.execution_service import ExecutionService
from pflow.registry import Registry
from pflow.runtime import compile_workflow
from tests.shared.markdown_utils import write_workflow_file

SH_PLAIN = "A shell command is plain sh: pflow never fills in ${…} there."


@pytest.fixture(scope="module")
def registry() -> Registry:
    reg = Registry()
    reg.load()
    return reg


def _cli(*args: str) -> Result:
    return CliRunner(mix_stderr=False).invoke(main, list(args))


def _shell(node_id: str, command: str, **extra: Any) -> dict[str, Any]:
    params = extra.pop("params", {})
    return {"id": node_id, "type": "shell", "params": {"command": command, **params}, **extra}


def _ir(*nodes: dict[str, Any], inputs: dict[str, Any] | None = None) -> dict[str, Any]:
    edges = [{"from": a["id"], "to": b["id"]} for a, b in pairwise(nodes)]
    ir: dict[str, Any] = {"ir_version": "0.1.0", "nodes": list(nodes), "edges": edges}
    if inputs:
        ir["inputs"] = inputs
    return ir


def _input(default: str) -> dict[str, Any]:
    return {"type": "string", "required": False, "default": default, "description": "An input."}


def _errors(diagnostics: list[Diagnostic]) -> list[Diagnostic]:
    return [d for d in diagnostics if d.severity is Severity.ERROR]


def _body_errors(ir: dict[str, Any]) -> list[Diagnostic]:
    return [
        d
        for d in _errors(validate_data_flow(ir))
        if "the command contains" in d.message or "code contains" in d.message
    ]


# ── 3. Every old-form shape is the ERROR at --validate-only, at the run, at compile ──


@dataclass(frozen=True)
class Shape:
    id: str
    ir: dict[str, Any]
    head: str  # the message up to the owner: "Step 's': the command contains ${item}"
    owner: str
    fixes: tuple[str, ...]  # fragments every suggestion list must hold
    params: dict[str, str] = field(default_factory=dict)


BATCH = {"items": ["ada"]}
LOOP = {"while": "${s.exit_code}", "max_iterations": 2}
ITEM_CLAUSE = "(${ITEM} where a letter, digit or _ follows; inside single quotes sh expands nothing — close them around it: '…'\"$ITEM\"'…')"

SHAPES = [
    Shape(
        "batch_item",
        _ir(_shell("s", 'echo "hello ${item}"', batch=BATCH)),
        "Step 's': the command contains ${item}",
        "this step's batch item",
        (
            'add `- env: {ITEM: ${item}}` to the step, then replace ${item} with "$ITEM" ' + ITEM_CLAUSE,
            "Only if the command itself assigns `item` (a shell variable of your own, e.g. `for item in …`)",
        ),
    ),
    Shape(
        "hyphenated_step",
        _ir(_shell("fetch-data", "echo payload"), _shell("s", 'echo "got: ${fetch-data.stdout}"')),
        "Step 's': the command contains ${fetch-data.stdout}",
        "step 'fetch-data'",
        (
            "add `- env: {FETCH_DATA_STDOUT: ${fetch-data.stdout}}` to the step",
            "it collides with step 'fetch-data' — rename the name in that program.",
        ),
    ),
    Shape(
        "dotted_step",
        _ir(_shell("a", "echo x"), _shell("s", "echo ${a.b}")),
        "Step 's': the command contains ${a.b}",
        "step 'a'",
        ("add `- env: {A_B: ${a.b}}` to the step",),
    ),
    Shape(
        "single_quoted_input",
        _ir(_shell("s", "[ '${overwrite}' = true ] && echo yes"), inputs={"overwrite": _input("true")}),
        "Step 's': the command contains ${overwrite}",
        "workflow input 'overwrite'",
        ("inside single quotes sh expands nothing — close them around it: '…'\"$OVERWRITE\"'…'",),
    ),
    Shape(
        "batch_index",
        _ir(_shell("s", "echo ${__index__}", batch=BATCH)),
        "Step 's': the command contains ${__index__}",
        "this step's batch index",
        ("add `- env: {INDEX: ${__index__}}` to the step",),
    ),
    Shape(
        "loop_iteration",
        _ir(_shell("s", "echo ${__iteration__}", loop=LOOP)),
        "Step 's': the command contains ${__iteration__}",
        "this step's loop iteration",
        ("add `- env: {ITERATION: ${__iteration__}}` to the step",),
    ),
    Shape(
        "inputs_key",
        _ir(_shell("s", "echo ${mode}", params={"inputs": {"mode": "fast"}})),
        "Step 's': the command contains ${mode}",
        "a key of this step's inputs:",
        ("add `- env: {MODE: ${mode}}` to the step",),
    ),
    Shape(
        "carry_key",
        _ir(
            _shell(
                "s",
                "echo ${state}",
                params={"inputs": {"state": "seed"}},
                loop={**LOOP, "carry": {"state": "${s.stdout}"}},
            )
        ),
        "Step 's': the command contains ${state}",
        "a key of this step's inputs:",
        ("add `- env: {STATE: ${state}}` to the step",),
    ),
    Shape(
        "forward_reference",
        _ir(_shell("s", "echo ${later.stdout}"), _shell("later", "echo late")),
        "Step 's': the command contains ${later.stdout}",
        "step 'later'",
        ("add `- env: {LATER_STDOUT: ${later.stdout}}` to the step",),
    ),
    Shape(
        "expansion_form_on_input",
        _ir(_shell("s", "head -n ${limit:-10} f"), inputs={"limit": _input("5")}),
        "Step 's': the command contains ${limit:-10}",
        "workflow input 'limit'",
        (
            'add `- env: {LIMIT: ${limit}}` to the step, then replace ${limit:-10} with "${LIMIT:-10}"',
            "Only if the command itself assigns `limit` (a shell variable of your own): rename it.",
        ),
    ),
    Shape(
        "expansion_form_on_batch_item",
        _ir(_shell("s", "echo ${#item}", batch=BATCH)),
        "Step 's': the command contains ${#item}",
        "this step's batch item",
        ('then replace ${#item} with "${#ITEM}"',),
    ),
    Shape(
        "whole_body_reference",
        _ir(_shell("producer", "echo 'echo hi'"), _shell("s", "${producer.stdout}")),
        "Step 's': the command contains ${producer.stdout}",
        "step 'producer'",
        (
            "The whole command is one pflow reference — bind it and run it: add `- env: {CMD: ${producer.stdout}}` "
            'to the step and make the command eval "$CMD".',
        ),
    ),
]


def _assert_leftover(diagnostic: Diagnostic, shape: Shape, location: str = "") -> None:
    assert diagnostic.message == f"{shape.head}{location} — a pflow reference ({shape.owner}). {SH_PLAIN}"
    suggestions = " || ".join(diagnostic.suggestions or [])
    missing = [fragment for fragment in shape.fixes if fragment not in suggestions]
    assert not missing, f"fix text must hold {missing}: {suggestions}"


@pytest.mark.parametrize("shape", [pytest.param(s, id=s.id) for s in SHAPES])
def test_old_form_reference_is_an_error_at_compile_on_a_dict_ir(shape: Shape, registry: Registry) -> None:
    """No WorkflowValidator in front: the compiler's own data-flow check refuses it."""
    with pytest.raises(CompilationError) as raised:
        compile_workflow(shape.ir, registry, initial_params={})
    [diagnostic] = [d for d in raised.value.wrapped_diagnostics or [] if "pflow reference" in d.message]
    _assert_leftover(diagnostic, shape)


@pytest.mark.parametrize("shape", [pytest.param(s, id=s.id) for s in SHAPES])
def test_old_form_reference_is_the_same_error_at_validate_only_and_at_the_run(shape: Shape, tmp_path: Path) -> None:
    path = tmp_path / "wf.pflow.md"
    write_workflow_file(shape.ir, path)
    if loop := shape.ir["nodes"][-1].get("loop"):  # the markdown writer has no loop block
        path.write_text(
            path.read_text(encoding="utf-8") + f"\n```yaml loop\n{yaml.safe_dump(loop)}```\n", encoding="utf-8"
        )
    line = next(
        n
        for n, text in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if "${" in text and "```" not in text and "- " not in text[:2]
    )

    validated = _cli("--validate-only", str(path))
    ran = _cli(str(path))

    assert validated.exit_code != 0 and ran.exit_code != 0
    expected = f"{shape.head} (line {line} of the workflow file) — a pflow reference ({shape.owner}). {SH_PLAIN}"
    assert expected in validated.output + validated.stderr
    assert expected in ran.output + ran.stderr
    assert "Workflow completed" not in ran.output + ran.stderr


def test_nothing_runs_before_the_leftover_is_reported(tmp_path: Path) -> None:
    proof = tmp_path / "ran.txt"
    ir = _ir(_shell("first", f"touch '{proof.as_posix()}'"), _shell("s", 'echo "${item}"', batch=BATCH))
    path = tmp_path / "wf.pflow.md"
    write_workflow_file(ir, path)
    assert _cli(str(path)).exit_code != 0
    assert not proof.exists()
    ir["nodes"][1]["params"]["command"] = 'echo "$item"'  # the presence half: the same workflow runs
    write_workflow_file(ir, path)
    assert _cli(str(path)).exit_code == 0
    assert proof.exists()


def test_several_leftovers_in_one_body_are_one_error_with_one_env_line() -> None:
    ir = _ir(
        _shell("fetch", "echo x"),
        _shell("s", 'echo "${fetch.stdout}"\necho "${item} ${limit}"', batch=BATCH),
        inputs={"limit": _input("3")},
    )
    ir["nodes"][1]["_source_lines"] = {"command": 30}
    [error] = _body_errors(ir)
    assert error.message == (
        "Step 's': the command contains 3 pflow references — ${fetch.stdout} (line 30, step 'fetch'), "
        "${item} (line 31, this step's batch item), ${limit} (line 31, workflow input 'limit'). " + SH_PLAIN
    )
    assert error.suggestions == [
        "Bind them: add `- env: {FETCH_STDOUT: ${fetch.stdout}, ITEM: ${item}, LIMIT: ${limit}}` to the step, "
        'then replace each with "$FETCH_STDOUT", "$ITEM", "$LIMIT" (${NAME} where a letter, digit or _ follows; '
        "inside single quotes sh expands nothing — close them around each)."
    ]
    assert error.context is not None
    assert error.context["source_line"] == 30
    assert error.context["body_references"] == [
        {"reference": "${fetch.stdout}", "owner": "step 'fetch'", "line": 30, "binding": "FETCH_STDOUT"},
        {"reference": "${item}", "owner": "this step's batch item", "line": 31, "binding": "ITEM"},
        {"reference": "${limit}", "owner": "workflow input 'limit'", "line": 31, "binding": "LIMIT"},
    ]


def test_any_reference_in_an_expression_makes_it_a_leftover() -> None:
    """The dependency view: a coalesce's later operand, a dynamic index's inner reference."""
    [coalesce] = _body_errors(_ir(_shell("s", "echo ${ghost.x ?? limit}"), inputs={"limit": _input("3")}))
    assert coalesce.message.startswith(
        "Step 's': the command contains ${ghost.x ?? limit} — a pflow reference (workflow input 'limit')"
    )
    [index] = _body_errors(_ir(_shell("s", "echo ${arr[${__index__}]}", batch=BATCH)))
    assert index.message.startswith(
        "Step 's': the command contains ${arr[${__index__}]} — a pflow reference (this step's batch index)"
    )


def test_a_colonless_default_on_an_in_scope_name_is_a_leftover() -> None:
    """sh reads ``${limit-10}`` as ``$limit`` with a default (sh names hold no ``-``), though
    pflow's grammar reads one name ``limit-10``: the in-scope ``limit`` makes it the ERROR."""
    [error] = _body_errors(_ir(_shell("s", "head -n ${limit-10} f"), inputs={"limit": _input("5")}))
    assert (
        error.message
        == f"Step 's': the command contains ${{limit-10}} — a pflow reference (workflow input 'limit'). {SH_PLAIN}"
    )
    assert (error.suggestions or [])[0].startswith(
        "Bind the value and read it as a shell variable: add `- env: {LIMIT: ${limit}}` to the step, then replace "
        '${limit-10} with "${LIMIT-10}" (inside single quotes'
    )
    assert _body_errors(_ir(_shell("s", "head -n ${count-10} f"))) == []  # `count` is no pflow name


def test_a_step_with_env_is_told_to_add_under_it() -> None:
    [error] = _body_errors(_ir(_shell("s", 'echo "${item}"', batch=BATCH, params={"env": {"OTHER": "x"}})))
    assert (error.suggestions or [])[0].startswith(
        "Bind the value and read it as a shell variable: add ITEM: ${item} under the step's existing env:, then"
    )


def test_a_child_workflow_leftover_carries_the_parent_provenance(tmp_path: Path, registry: Registry) -> None:
    child = tmp_path / "child.pflow.md"
    write_workflow_file(_ir(_shell("inner", 'echo "${who}"'), inputs={"who": _input("x")}), child)
    parent = _ir({"id": "run-child", "type": "workflow", "params": {"workflow": str(child), "inputs": {"who": "ada"}}})
    errors = _errors(
        WorkflowValidator.validate(
            parent, extracted_params={}, registry=registry, workflow_file=tmp_path / "p.pflow.md"
        )
    )
    [error] = [d for d in errors if "pflow reference" in d.message]
    assert error.message.startswith(
        "In step 'run-child' sub-workflow: Step 'inner': the command contains ${who} (line "
    )
    assert error.context is not None and error.context["sub_workflow_step"] == "run-child"


def test_a_file_loaded_body_cites_its_script_and_line(tmp_path: Path) -> None:
    (tmp_path / "cmd.sh").write_text('set -e\necho "${item}"\n', encoding="utf-8")
    path = tmp_path / "wf.pflow.md"
    path.write_text(
        "# Script\n\nRuns a script per item.\n\n## Steps\n\n### s\n\nRun it.\n\n- type: shell\n- command: ./cmd.sh\n"
        "- batch:\n    items: [ada]\n",
        encoding="utf-8",
    )
    result = _cli("--validate-only", str(path))
    assert result.exit_code != 0
    assert (
        "Step 's': the command contains ${item} (line 2 of ./cmd.sh) — a pflow reference"
        in result.output + result.stderr
    )


# ── 4. False positives: valid, and sh prints what sh prints ─────────────────


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        # sh's own HOME (Git Bash may re-spell the inherited one): ${HOME} is expanded, never literal
        ('[ -n "$HOME" ] && [ "${HOME}" = "$HOME" ] && echo same', "same"),
        ('CI=yes; echo "${CI}"', "yes"),
        ('echo "${PFLOW_T118_UNSET:-y}"', "y"),
        ('X=abc; echo "${#X}"', "3"),
        ("bash -c 'arr=(a b); echo \"${arr[@]}\"'", "a b"),
        ('set -- one; echo "${1}"', "one"),
        ('X=x; echo "$$${X}" | sed "s/^[0-9]*/PID/"', "PIDx"),
        ("bash -c 'arr=(q r); echo \"${arr[0]}\"'", "q"),
    ],
    ids=[
        "home",
        "ci",
        "default_form",
        "length_form",
        "bash_array",
        "positional",
        "pid_then_var",
        "array_index",
    ],
)
def test_shell_syntax_is_valid_and_runs_unescaped(command: str, expected: str) -> None:
    ir = _ir(_shell("s", command))
    validation = WorkflowRunner().validate(ir, {})
    assert validation.errors == [] and validation.warnings == [], [d.message for d in validation.diagnostics]
    result = WorkflowRunner().run(ir, {}, RunnerConfig())
    assert result.success, [d.message for d in result.errors]
    assert result.shared_after["s"]["stdout"].strip() == expected


def test_batch_alias_shapes_that_are_not_pflow_references_run() -> None:
    """An unbraced ``$item`` on the batch step; ``for item`` on a NON-batch step beside it;
    a bare ``${count}`` where ``count`` is a step id."""
    ir = _ir(
        _shell("count", "echo 1"),
        _shell("b", 'echo "[$item]"', batch={"items": ["x", "y"]}),
        _shell("loop", 'for item in a b; do printf "%s" "${item}"; done; count=3; echo " ${count}"'),
    )
    assert _errors(WorkflowValidator.validate(ir, extracted_params={}, registry=Registry())) == []
    result = WorkflowRunner().run(ir, {}, RunnerConfig())
    assert result.success, [d.message for d in result.errors]
    assert [r["stdout"].strip() for r in result.shared_after["b"]["results"]] == ["[]", "[]"]
    assert result.shared_after["loop"]["stdout"].strip() == "ab 3"


# ── 5. The checkpoint's hard cases ──────────────────────────────────────────


def test_hard_case_a_a_pflow_name_that_is_also_a_shell_name() -> None:
    [error] = _body_errors(_ir(_shell("s", 'echo "${HOME}"', params={"inputs": {"HOME": "/x"}})))
    assert (
        error.message
        == f"Step 's': the command contains ${{HOME}} — a pflow reference (a key of this step's inputs:). {SH_PLAIN}"
    )
    assert error.suggestions is not None
    assert "add `- env: {HOME_VALUE: ${HOME}}` to the step" in error.suggestions[0]
    assert error.suggestions[1] == "If you meant the shell's own $HOME: write $HOME without braces."
    [alias] = _body_errors(_ir(_shell("s", 'echo "${PATH}"', batch={"items": ["a"], "as": "PATH"})))
    assert "(this step's batch item)" in alias.message
    assert (
        alias.suggestions is not None
        and alias.suggestions[1] == "If you meant the shell's own $PATH: write $PATH without braces."
    )
    assert (
        _body_errors(_ir(_shell("s", 'echo "$HOME"', params={"inputs": {"HOME": "/x"}, "env": {"H": "${HOME}"}}))) == []
    )


def test_hard_case_b_a_loop_variable_named_like_the_batch_alias() -> None:
    body = 'for item in a b; do echo "${item}"; done'
    [error] = _body_errors(_ir(_shell("s", body, batch=BATCH)))
    assert "(this step's batch item)" in error.message
    assert error.suggestions is not None
    assert error.suggestions[1] == (
        "Only if the command itself assigns `item` (a shell variable of your own, e.g. `for item in …`): "
        "write $item without braces, or rename it."
    )
    assert validate_data_flow(_ir(_shell("other", "echo x", batch=BATCH), _shell("s", body))) == []


def test_hard_case_d_another_languages_syntax() -> None:
    command = "node -e 'console.log(`${user.name}`)'"
    diagnostics = validate_data_flow(_ir(_shell("s", command)))
    assert [(d.severity, d.message) for d in diagnostics] == [
        (
            Severity.WARNING,
            "Step 's': ${user.name} in the command is not something sh can expand, and 'user' is not a step or "
            "input in this workflow. pflow never fills in ${…} in a command.",
        )
    ]
    assert diagnostics[0].suggestions == [
        'To use a pflow value, bind it in env: and read "$NAME". If the text belongs to another program inside '
        "the command, leave it."
    ]
    [error] = _body_errors(_ir(_shell("s", command), inputs={"user": _input("u")}))
    assert error.suggestions is not None
    assert error.suggestions[1] == (
        "If ${user.name} belongs to another program inside the command (a JavaScript template literal, say), "
        "it collides with workflow input 'user' — rename the name in that program."
    )


def test_ruling_2_offers_the_close_step_name() -> None:
    [warning] = validate_data_flow(_ir(_shell("fetch", "echo x"), _shell("s", 'echo "got: ${fecth.stdout}"')))
    assert warning.severity is Severity.WARNING
    assert warning.suggestions == [
        "Did you mean 'fetch'? Bind it: add `- env: {FETCH_STDOUT: ${fetch.stdout}}` to the step and read "
        '"$FETCH_STDOUT". If the text belongs to another program inside the command, leave it.'
    ]


def test_ruling_2_warning_never_fails_the_compile(registry: Registry) -> None:
    ir = _ir(_shell("s", "echo '${fecth.stdout}'"))
    assert compile_workflow(ir, registry, initial_params={}) is not None


def test_nameless_expansion_forms_are_never_leftovers() -> None:
    """``${#}``, ``${!}``, ``${}`` start with no name: never a leftover, never a crash —
    even with every name in scope."""
    ir = _ir(_shell("s", "echo ${#} ${!} ${} ${#item}x", batch=BATCH), inputs={"x": _input("1")})
    assert [ref.written for ref in body_references(ir["nodes"][0], step_scope(ir, ir["nodes"][0]))] == ["${#item}"]


def test_hard_case_e_bash_array_index() -> None:
    assert validate_data_flow(_ir(_shell("s", 'echo "${arr[0]}"'))) == []
    [error] = _body_errors(_ir(_shell("s", 'echo "${arr[0]}"'), inputs={"arr": _input("[]")}))
    assert "the command contains ${arr[0]}" in error.message


def test_hard_case_f_a_python_fstring_printing_a_dollar_amount() -> None:
    code = 'total: int\nresult: str = f"Total: ${total}"'
    ir = _ir({"id": "c", "type": "code", "params": {"inputs": {"total": 42}, "code": code}})
    assert validate_data_flow(ir) == []
    result = WorkflowRunner().run(ir, {}, RunnerConfig())
    assert result.success, [d.message for d in result.errors]
    assert result.shared_after["c"]["result"] == "Total: $42"


# ── 6. $${ in a body ─────────────────────────────────────────────────────────


def test_escape_in_a_shell_body_is_an_error() -> None:
    ir = _ir(_shell("price", 'echo "Price: $${PRICE} home=$HOME"'))
    ir["nodes"][0]["_source_lines"] = {"command": 13}
    [error] = _errors(validate_data_flow(ir))
    assert error.message == (
        "Step 'price': the command contains the escape $${PRICE} (line 13 of the workflow file). A shell command "
        "is plain sh, so there is nothing to escape — sh would run $$ as its process id, followed by {PRICE}."
    )
    assert error.suggestions == ["Write ${PRICE} for a shell expansion."]


def test_escape_of_an_in_scope_reference_offers_the_dollar_then_value_form() -> None:
    [error] = _errors(validate_data_flow(_ir(_shell("x", "echo 1"), _shell("s", 'echo "cost: $${x.cost}"'))))
    assert error.suggestions == [
        "For a dollar sign followed by the value: add `- env: {X_COST: ${x.cost}}` to the step and write "
        '\\$$X_COST inside double quotes — e.g. "value: \\$$X_COST".'
    ]


def test_escape_in_a_code_body_is_an_error() -> None:
    ir = _ir({"id": "c", "type": "code", "params": {"inputs": {}, "code": 'result: str = "Price: $${PRICE}"'}})
    [error] = _errors(validate_data_flow(ir))
    assert error.message == (
        "Step 'c': the code contains the escape $${PRICE} inside a Python string. A code step's code is plain "
        "Python, so there is nothing to escape — the string keeps both dollar signs."
    )
    assert error.suggestions == [
        "Python needs no escape: write ${PRICE} as plain text. For the literal characters $${ split the string: "
        '"$$" "{PRICE}".'
    ]


def test_pid_before_a_shell_expansion_is_not_an_escape() -> None:
    assert validate_data_flow(_ir(_shell("s", 'echo "$$${X}"'))) == []


# ── 7. Code bodies ───────────────────────────────────────────────────────────


def test_code_string_reference_names_inputs() -> None:
    ir = _ir(
        {"id": "up", "type": "code", "params": {"inputs": {}, "code": 'result: str = "${name}".upper()'}},
        inputs={"name": _input("bob")},
    )
    ir["nodes"][0]["_source_lines"] = {"code": 21}
    [error] = _body_errors(ir)
    assert error.message == (
        "Step 'up': the code contains \"${name}\" (line 21 of the workflow file) — a pflow reference (workflow "
        "input 'name') inside a Python string. A code step's code is plain Python: pflow never fills in ${…} there."
    )
    assert error.suggestions == [
        "Declare it in inputs: — add `- inputs: {name: ${name}}` to the step, declare its type in the code "
        "(`name: str`), and use the variable `name` in place of the string."
    ]
    assert error.see_also == ["code"]


def test_code_reference_to_an_existing_input_key_says_use_the_variable() -> None:
    code = 'name: str\nresult: str = """\nHi ${name}\n"""'
    [error] = _body_errors(_ir({"id": "c", "type": "code", "params": {"inputs": {"name": "x"}, "code": code}}))
    assert error.suggestions == [
        "'name' is already bound by inputs: — use the variable name instead of the string \"${name}\"."
    ]
    assert error.context is not None and error.context["body_references"][0]["line"] is None


def test_code_leftover_line_counts_newlines_inside_a_triple_quoted_string() -> None:
    code = 'x: str\nresult: str = """\nfirst\n${x}\n"""'
    ir = _ir({"id": "c", "type": "code", "params": {"inputs": {"x": "v"}, "code": code}})
    ir["nodes"][0]["_source_lines"] = {"code": 10}
    [error] = _body_errors(ir)
    assert error.context is not None and error.context["source_line"] == 13  # body line 3 (0-based)


def test_code_without_references_runs_unchanged() -> None:
    ir = _ir({"id": "c", "type": "code", "params": {"inputs": {}, "code": 'result: str = "a $ b {c}"'}})
    assert validate_data_flow(ir) == []
    result = WorkflowRunner().run(ir, {}, RunnerConfig())
    assert result.shared_after["c"]["result"] == "a $ b {c}"


def test_code_python_cannot_parse_is_left_to_its_parser(tmp_path: Path) -> None:
    """A dict IR reaches the rule unparsed by the markdown parser: no leftover, no crash."""
    ir = _ir(
        {"id": "c", "type": "code", "params": {"inputs": {}, "code": "result: str = ${name}"}},
        inputs={"name": _input("x")},
    )
    assert validate_data_flow(ir) == []


def test_code_with_a_syntax_error_gets_the_parsers_error_only(tmp_path: Path) -> None:
    path = tmp_path / "wf.pflow.md"
    path.write_text(
        "# Bad\n\nBad code.\n\n## Inputs\n\n### name\n\nA name.\n\n- type: string\n\n## Steps\n\n### c\n\nRun.\n\n"
        "- type: code\n\n```python code\nresult: str = ${name}\n```\n",
        encoding="utf-8",
    )
    result = _cli("--validate-only", str(path), "name=x")
    text = result.output + result.stderr
    assert result.exit_code != 0
    assert "syntax" in text.lower()
    assert "pflow reference" not in text


# ── 8. One mistake, one diagnostic ───────────────────────────────────────────


def test_an_input_read_only_through_a_leftover_gets_the_leftover_error_alone(registry: Registry) -> None:
    ir = _ir(_shell("s", 'echo "${name}"'), inputs={"name": _input("x")})
    messages = [
        d.message for d in _errors(WorkflowValidator.validate(ir, extracted_params={"name": "x"}, registry=registry))
    ]
    assert [m for m in messages if "pflow reference" in m] and not [m for m in messages if "never used" in m], messages
    ir["nodes"][0]["params"]["command"] = "echo hi"
    messages = [
        d.message for d in _errors(WorkflowValidator.validate(ir, extracted_params={"name": "x"}, registry=registry))
    ]
    assert [m for m in messages if "never used" in m] == ["Declared input(s) never used as template variable: name"]


# ── 10, 11, 14. Real surfaces ─────────────────────────────────────────────────


def test_a_file_loaded_script_with_shell_syntax_runs(tmp_path: Path) -> None:
    (tmp_path / "cmd.sh").write_text(
        '[ -n "$HOME" ] && [ "${HOME}" = "$HOME" ] && echo "${NAME:-x} same"\n', encoding="utf-8"
    )
    path = tmp_path / "wf.pflow.md"
    path.write_text(
        "# Script\n\nRuns a script.\n\n## Steps\n\n### s\n\nRun it.\n\n- type: shell\n- command: ./cmd.sh\n",
        encoding="utf-8",
    )
    result = _cli(str(path))
    assert result.exit_code == 0, result.output + result.stderr
    assert "x same" in result.output


def test_mcp_single_node_run_leaves_a_body_to_sh() -> None:
    output = ExecutionService.run_registry_node("shell", {"command": 'for f in a b; do echo "${f}"; done'})
    assert "a\nb" in output, output


def test_checkpoint_probe_validates_and_prints_what_sh_prints(tmp_path: Path) -> None:
    path = tmp_path / "forms.pflow.md"
    path.write_text(
        "# Forms\n\nShell syntax.\n\n## Steps\n\n### forms\n\nPrint.\n\n- type: shell\n\n"
        '```shell command\nX=abc; echo "${NAME:-world} ${#X} ${HOME}"\n```\n',
        encoding="utf-8",
    )
    validated = _cli("--validate-only", str(path))
    assert validated.exit_code == 0 and "Workflow is valid" in validated.output, validated.output + validated.stderr
    ran = _cli(str(path))
    assert ran.exit_code == 0
    [line] = [text for text in ran.output.splitlines() if text.startswith("world 3 ")]
    assert line != "world 3 " and "${" not in line  # sh expanded ${HOME}


# ── PB mid-task review: shapes the first cut missed ──────────────────────────


def test_a_bytes_literal_is_read_like_a_string() -> None:
    """``b"${name}".decode()`` was resolved before; it must fail, not return the literal text."""
    code = 'name: str\nresult: str = b"${name}".decode()'
    [error] = _body_errors(_ir({"id": "c", "type": "code", "params": {"inputs": {"name": "bob"}, "code": code}}))
    assert error.message.startswith(
        "Step 'c': the code contains \"${name}\" — a pflow reference (a key of this step's inputs:)"
    )
    escape = _ir({"id": "c", "type": "code", "params": {"inputs": {}, "code": 'result: str = b"$${X}".decode()'}})
    assert [d.message.split(" (")[0] for d in _errors(validate_data_flow(escape))] == [
        "Step 'c': the code contains the escape $${X} inside a Python string. A code step's code is plain Python, "
        "so there is nothing to escape — the string keeps both dollar signs."
    ]


@pytest.mark.parametrize(
    ("command", "written", "step"),
    [
        (
            'printf %s "${limit-default:value}"',
            "${limit-default:value}",
            _shell("s", "", params={"inputs": {"limit": 5}}),
        ),
        ('printf %s "${item-fallback value}"', "${item-fallback value}", _shell("s", "", batch=BATCH)),
    ],
    ids=["colon_in_default", "space_in_default"],
)
def test_a_colonless_default_the_parser_reads_as_an_issue_is_a_leftover(
    command: str, written: str, step: dict[str, Any]
) -> None:
    step["params"]["command"] = command
    [error] = _body_errors(_ir(step))
    assert f"the command contains {written} — a pflow reference" in error.message


def test_an_in_scope_reference_nested_in_a_shell_expansion_is_a_leftover() -> None:
    """``${UNSET:-${item}}`` is one Issue to the parser (it ends at the first ``}``); the
    ``${item}`` inside it was resolved before and must not run empty now."""
    ir = _ir(_shell("s", 'printf %s "${PFLOW_T118_UNSET:-${item}}"', batch=BATCH))
    [error] = _body_errors(ir)
    assert error.message.startswith(
        "Step 's': the command contains ${item} — a pflow reference (this step's batch item)"
    )
    assert _body_errors(_ir(_shell("s", 'printf %s "${PFLOW_T118_UNSET:-${HOME}}"', batch=BATCH))) == []


def test_the_prescribed_escape_split_validates_and_runs_beside_another_reference() -> None:
    """Checkpoint §3's repair, ``"$$" "{PRICE}"``, must stay valid when the body also holds a
    legitimate ``${…}`` (which is what makes the rule read the body at all)."""
    code = 'result: str = "$$" "{PRICE}" + "${HOME}"'
    ir = _ir({"id": "c", "type": "code", "params": {"inputs": {}, "code": code}})
    assert validate_data_flow(ir) == []
    result = WorkflowRunner().run(ir, {}, RunnerConfig())
    assert result.success, [d.message for d in result.errors]
    assert result.shared_after["c"]["result"] == "$${PRICE}${HOME}"


@pytest.mark.parametrize(
    ("command", "inputs"),
    [('echo "${primary ?? fallback}"', ("primary", "fallback")), ('echo "${values[${index}]}"', ("values", "index"))],
    ids=["coalesce", "dynamic_index"],
)
def test_every_input_a_leftover_names_counts_as_used(command: str, inputs: tuple[str, str], registry: Registry) -> None:
    ir = _ir(_shell("s", command), inputs={name: _input("x") for name in inputs})
    messages = [d.message for d in _errors(WorkflowValidator.validate(ir, extracted_params={}, registry=registry))]
    assert len(messages) == 1 and "pflow reference" in messages[0], messages


def test_every_inputs_key_a_leftover_names_is_left_to_that_error(registry: Registry) -> None:
    step = _shell("s", 'echo "${a ?? b}"', params={"inputs": {"a": "1", "b": "2"}})
    warnings = [
        d
        for d in WorkflowValidator.validate(_ir(step), extracted_params={}, registry=registry)
        if "not visible" in d.message
    ]
    assert warnings == []


# ── Completion gate: shapes and fixes the phase reviews missed ───────────────


def test_ruling_2_sees_a_misspelled_reference_nested_in_a_shell_expansion() -> None:
    """``${UNSET:-${fecth-data.stdout}}`` is one Issue to the parser; sh silently prints the
    default's default (``data.stdout``), so the nested typo warns exactly like a bare one."""
    ir = _ir(
        _shell("fetch-data", "echo x"),
        _shell("s", 'echo start\nprintf %s "${PFLOW_T118_UNSET:-${fecth-data.stdout}}"'),
    )
    ir["nodes"][1]["_source_lines"] = {"command": 7}
    [warning] = validate_data_flow(ir)
    assert warning.severity is Severity.WARNING
    assert warning.message == (
        "Step 's': ${fecth-data.stdout} in the command is not something sh can expand, and 'fecth-data' is not "
        "a step or input in this workflow. pflow never fills in ${…} in a command."
    )
    assert warning.suggestions is not None and warning.suggestions[0].startswith("Did you mean 'fetch-data'?")
    assert warning.context is not None and warning.context["source_line"] == 8


def test_a_comment_between_adjacent_python_literals_is_not_string_text() -> None:
    """Python joins ``"a" "b"`` into one constant whose source span holds the comment
    between them; the comment is not a string, so a ``${…}`` there is not a leftover."""
    code = 'name: str\nresult: str = (\n    "hello "  # ${name} and $${X} only in a comment\n    "world"\n)'
    ir = _ir({"id": "c", "type": "code", "params": {"inputs": {"name": "Ada"}, "code": code}})
    assert validate_data_flow(ir) == []
    result = WorkflowRunner().run(ir, {}, RunnerConfig())
    assert result.success, [d.message for d in result.errors]
    assert result.shared_after["c"]["result"] == "hello world"
    # Presence: the same reference inside the second literal is still read, on its own line.
    leftover = 'name: str\nresult: str = (\n    "hello "  # a comment\n    "${name}"\n)'
    ir = _ir({"id": "c", "type": "code", "params": {"inputs": {"name": "Ada"}, "code": leftover}})
    ir["nodes"][0]["_source_lines"] = {"code": 10}
    [error] = _body_errors(ir)
    assert error.message.startswith("Step 'c': the code contains \"${name}\" (line 13 of the workflow file)")


@pytest.mark.parametrize(
    ("value", "reference", "access"),
    [({"name": "ada"}, "user.name", "user['name']"), ([{"name": "ada"}], "user[0].name", "user[0]['name']")],
    ids=["field", "index_then_field"],
)
def test_code_reference_to_a_field_of_an_input_key_says_how_to_read_the_field(
    value: Any, reference: str, access: str
) -> None:
    """The variable holds the whole input; the fix reads the field, and the fix runs."""
    annotation = "dict" if isinstance(value, dict) else "list"
    code = f'user: {annotation}\nresult: str = "${{{reference}}}".upper()'
    [error] = _body_errors(_ir({"id": "c", "type": "code", "params": {"inputs": {"user": value}, "code": code}}))
    assert error.suggestions == [
        f"'user' is already bound by inputs: — use {access} instead of the string \"${{{reference}}}\"."
    ]
    fixed = _ir({
        "id": "c",
        "type": "code",
        "params": {"inputs": {"user": value}, "code": f"user: {annotation}\nresult: str = {access}.upper()"},
    })
    result = WorkflowRunner().run(fixed, {}, RunnerConfig())
    assert result.success, [d.message for d in result.errors]
    assert result.shared_after["c"]["result"] == "ADA"


def test_an_expansion_form_on_an_upper_case_alias_suggests_a_name_outside_the_scope() -> None:
    """``as: LIMIT``: the suggested ``"${LIMIT:-10}"`` would be the same leftover again."""
    batch = {"items": [3], "as": "LIMIT"}
    [error] = _body_errors(_ir(_shell("s", "seq ${LIMIT:-10}", batch=batch)))
    assert error.suggestions is not None
    assert error.suggestions[0].startswith(
        "Bind the value and read it as a shell variable: add `- env: {LIMIT_VALUE: ${LIMIT}}` to the step, then "
        'replace ${LIMIT:-10} with "${LIMIT_VALUE:-10}"'
    )
    fixed = _ir(_shell("s", 'seq "${LIMIT_VALUE:-10}"', batch=batch, params={"env": {"LIMIT_VALUE": "${LIMIT}"}}))
    assert validate_data_flow(fixed) == []
    result = WorkflowRunner().run(fixed, {}, RunnerConfig())
    assert result.success, [d.message for d in result.errors]
    assert result.shared_after["s"]["results"][0]["stdout"].split() == ["1", "2", "3"]


def test_code_escape_of_an_in_scope_reference_declares_the_type_and_the_fix_runs(registry: Registry) -> None:
    ir = _ir(
        {"id": "c", "type": "code", "params": {"code": 'result: str = "$${name}"'}}, inputs={"name": _input("bob")}
    )
    [error] = _errors(validate_data_flow(ir))
    assert error.suggestions == [
        "For a dollar sign followed by the value: add `- inputs: {name: ${name}}` to the step, declare its type in "
        'the code (`name: str`), and write f"${name}".'
    ]
    fixed = _ir(
        {
            "id": "c",
            "type": "code",
            "params": {"inputs": {"name": "${name}"}, "code": 'name: str\nresult: str = f"${name}"'},
        },
        inputs={"name": _input("bob")},
    )
    assert _errors(WorkflowValidator.validate(fixed, extracted_params={}, registry=registry)) == []
    result = WorkflowRunner().run(fixed, {}, RunnerConfig())
    assert result.success, [d.message for d in result.errors]
    assert result.shared_after["c"]["result"] == "$bob"


def test_a_step_whose_env_is_one_template_is_told_to_extend_that_map(registry: Registry) -> None:
    """A second ``- env:`` bullet would replace ``env: ${cfg.stdout}`` (the parser keeps the
    last), dropping whatever that map binds — so neither fix says "add `- env:`"."""
    extend = (
        "add URL: ${url} to the map that the step's env: ${cfg.stdout} produces (a second `- env:` would replace it)"
    )
    leftover = _ir(
        _shell("cfg", "echo '{}'"),
        _shell("s", 'curl "${url}"', params={"env": "${cfg.stdout}"}),
        inputs={"url": _input("x")},
    )
    [error] = _body_errors(leftover)
    assert error.suggestions is not None
    assert error.suggestions[0].startswith(f"Bind the value and read it as a shell variable: {extend}, then replace")
    unread = _ir(
        _shell("cfg", "echo '{}'"), _shell("s", "curl x", params={"env": "${cfg.stdout}", "inputs": {"url": "x"}})
    )
    [warning] = [
        d
        for d in WorkflowValidator.validate(unread, extracted_params={}, registry=registry)
        if "not visible" in d.message
    ]
    assert warning.suggestions == [f'Bind it: {extend} and read "$URL" in the command — or remove the key.']
