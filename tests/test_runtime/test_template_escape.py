"""End-to-end tests for the `$${...}` escape (issue #620).

`$${` is the escape for a literal `${`: any content after it is left alone and the
resolved value carries a single `$`. These run real `shell` workflows through
`WorkflowRunner`, so parsing, validation, param routing and resolution are all
exercised together. The escape rides a templated param (`stdin`, echoed by `cat`).
"""

from typing import Any

from pflow.execution.result import ExecutionResult, RunnerConfig
from pflow.execution.runner import WorkflowRunner

# The escape from docs/how-it-works/template-variables.mdx ("Escaping"), wrapped in
# the minimal workflow the issue used to reproduce it.
DOCS_ESCAPE_EXAMPLE = """\
# Escape Example

Prints a literal `${PRICE}`.

## Steps

### print_price

Print the literal price variable.

- type: shell
- stdin: "Price: $${PRICE}"

```shell command
cat
```
"""


def _shell_workflow(stdin: str, inputs: str = "", params: str = "", command: str = "cat") -> str:
    stdin_line = f"- stdin: {stdin}\n" if stdin else ""
    return f"""\
# Escape Test
{inputs}
## Steps

### run

Run the command.

- type: shell
{stdin_line}{params}
```shell command
{command}
```
"""


def _run(markdown: str, params: dict[str, Any] | None = None) -> ExecutionResult:
    return WorkflowRunner().run(markdown, params or {}, RunnerConfig(trace_enabled=False))


def _stdout(result: ExecutionResult, node_id: str) -> str:
    assert result.success, [e.get("message") for e in result.errors]
    stdout: str = result.shared_after[node_id]["stdout"]
    return stdout.strip()


def test_docs_escape_example_prints_literal_template() -> None:
    assert _stdout(_run(DOCS_ESCAPE_EXAMPLE), "print_price") == "Price: ${PRICE}"


def test_escape_with_shell_parameter_expansion_validates_and_stays_literal() -> None:
    """Non-identifier content (`:-default`) validates and arrives as `${...}`, unexpanded."""
    result = _run(_shell_workflow('"$${PFLOW_TEST_UNSET_620:-world}"'))
    assert _stdout(result, "run") == "${PFLOW_TEST_UNSET_620:-world}"


def test_escape_and_reference_of_same_name_in_different_steps_do_not_interact() -> None:
    inputs = """
## Inputs

### name

A name.

- type: string
- required: true
"""
    workflow = _shell_workflow('"hello ${name}"', inputs).replace(
        "## Steps\n",
        '## Steps\n\n### literal\n\nPrint a literal.\n\n- type: shell\n- stdin: "$${name}"\n\n'
        "```shell command\ncat\n```\n",
    )
    result = _run(workflow, {"name": "Ada"})
    assert _stdout(result, "literal") == "${name}"
    assert _stdout(result, "run") == "hello Ada"


def test_bare_double_dollar_is_not_an_escape() -> None:
    """`$$` without a following `{` is plain text (the shell's PID here)."""
    result = _run(_shell_workflow("", command="echo \"$$\" | grep -Eq '^[0-9]+$' && echo pid"))
    assert _stdout(result, "run") == "pid"


def test_escape_in_batch_step_resolves_per_item() -> None:
    workflow = _shell_workflow('"${item} $${PFLOW_TEST_UNSET_620:-none}"').replace(
        "- type: shell\n", '- type: shell\n- batch:\n    items: ["a", "b"]\n'
    )
    result = _run(workflow)
    assert result.success, [e.get("message") for e in result.errors]
    batch = result.shared_after["run"]
    assert [r["stdout"].strip() for r in batch["results"]] == [
        "a ${PFLOW_TEST_UNSET_620:-none}",
        "b ${PFLOW_TEST_UNSET_620:-none}",
    ]
