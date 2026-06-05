"""Validation-matrix coverage for the `loop:` config block (issue #445, Phase 3).

Exercises the cross-layer carve-outs in data_flow.py + template_validation that
are the highest silent-drift area:
- typed-output gate (known-string `while:` rejected; `any`/un-inferable allowed)
- operator rejection in `while:`
- loop self-reference carve-out (allowed for the loop node, rejected otherwise)
- `${__iteration__}` reserved-key handling (bare allowed, path access rejected)
- `loop:` + `storage_mode: shared` rejection
- an input used only in `while:` is NOT flagged unused
"""

import pytest

from pflow.core.diagnostic import Severity
from pflow.core.workflow.validator import WorkflowValidator
from pflow.registry import Registry


@pytest.fixture(scope="module")
def registry() -> Registry:
    reg = Registry()
    reg.load()
    return reg


def _errors(ir, registry):
    return [
        d
        for d in WorkflowValidator.validate(ir, extracted_params={}, registry=registry)
        if d.severity == Severity.ERROR
    ]


def _diagnostics(ir, registry):
    return WorkflowValidator.validate(ir, extracted_params={}, registry=registry)


def _ir(nodes, inputs=None):
    ir = {"ir_version": "0.1.0", "nodes": nodes, "edges": []}
    if inputs:
        ir["inputs"] = inputs
    return ir


def _shell_loop(while_expr, max_it=3):
    return _ir([
        {
            "id": "c",
            "type": "shell",
            "params": {"command": "echo hi"},
            "loop": {"while": while_expr, "max_iterations": max_it},
        }
    ])


def test_known_string_while_rejected(registry) -> None:
    # shell.stdout is typed `str` in the registry → string-truthiness foot-gun.
    errs = _errors(_shell_loop("${c.stdout}"), registry)
    assert any("string" in d.message for d in errs)


def test_int_typed_while_passes(registry) -> None:
    # shell.exit_code is typed int → fine.
    assert _errors(_shell_loop("${c.exit_code}"), registry) == []


def test_operator_while_rejected(registry) -> None:
    errs = _errors(_shell_loop("${c.exit_code > 0}"), registry)
    assert any("operator" in d.message for d in errs)


def test_multi_reference_while_rejected(registry) -> None:
    # `${c.stdout}${c.stderr}` passes the broad schema pattern (^\$\{.+\}$) but is not a
    # single ${...} reference. It must be rejected HERE, not silently single-passed at
    # runtime (the validator and runtime previously each deferred to the other — review #6).
    errs = _errors(_shell_loop("${c.stdout}${c.stderr}"), registry)
    assert any("single" in d.message for d in errs)


def test_coalesce_while_with_string_operand_rejected(registry) -> None:
    # ${c.stdout ?? "x"} — c.stdout is str → string-truthiness foot-gun must be
    # caught at validation, not deferred to the runtime belt (review fix).
    errs = _errors(_shell_loop('${c.stdout ?? "done"}'), registry)
    assert any("string" in d.message.lower() for d in errs)


def test_coalesce_while_with_typed_operand_passes(registry) -> None:
    # ${c.exit_code ?? 0} — both operands non-string (int / literal) → allowed.
    assert _errors(_shell_loop("${c.exit_code ?? 0}"), registry) == []


def test_any_typed_while_passes(registry) -> None:
    # A workflow node whose child output is un-inferable resolves to `any`.
    ir = _ir([
        {
            "id": "c",
            "type": "workflow",
            "params": {"workflow": "./child.pflow.md"},
            "loop": {"while": "${c.items}", "max_iterations": 3},
        }
    ])
    # No "string"/operator rejection from the loop-condition pass (sub-workflow
    # resolution errors may appear, but not a typed-output gate rejection).
    errs = _errors(ir, registry)
    assert not any("String truthiness" in d.message for d in errs)


def test_iteration_path_access_rejected(registry) -> None:
    ir = _ir([
        {
            "id": "c",
            "type": "shell",
            "params": {"command": "echo ${__iteration__.foo}"},
            "loop": {"while": "${c.exit_code}", "max_iterations": 3},
        }
    ])
    errs = _errors(ir, registry)
    assert any("__iteration__" in d.message for d in errs)


def test_bare_iteration_allowed(registry) -> None:
    ir = _ir([
        {
            "id": "c",
            "type": "shell",
            "params": {"command": "echo ${__iteration__}"},
            "loop": {"while": "${c.exit_code}", "max_iterations": 3},
        }
    ])
    assert _errors(ir, registry) == []


def test_self_reference_in_while_allowed_for_loop_node(registry) -> None:
    # ${c.exit_code} is a self-reference on the loop node — allowed.
    assert _errors(_shell_loop("${c.exit_code}"), registry) == []


def test_while_referencing_nonexistent_node_rejected(registry) -> None:
    errs = _errors(_shell_loop("${typo.x}"), registry)
    assert any("non-existent" in d.message or "typo" in d.message for d in errs)


def test_storage_mode_shared_plus_loop_rejected(registry) -> None:
    ir = _ir([
        {
            "id": "c",
            "type": "workflow",
            "params": {"workflow": "./child.pflow.md", "storage_mode": "shared"},
            "loop": {"while": "${c.items}", "max_iterations": 3},
        }
    ])
    errs = _errors(ir, registry)
    assert any("storage_mode: shared" in d.message for d in errs)


def test_loop_under_disabled_namespacing_rejected(registry) -> None:
    ir = _ir([
        {
            "id": "c",
            "type": "shell",
            "params": {"command": "echo hi"},
            "loop": {"while": "${c.exit_code}", "max_iterations": 3},
        }
    ])
    ir["enable_namespacing"] = False
    errs = _errors(ir, registry)
    assert any("enable_namespacing" in d.message for d in errs)


def test_input_used_only_in_while_not_flagged_unused(registry) -> None:
    ir = _ir(
        [
            {
                "id": "c",
                "type": "shell",
                "params": {"command": "echo hi"},
                "loop": {"while": "${threshold}", "max_iterations": 3},
            }
        ],
        inputs={"threshold": {"type": "any", "required": True}},
    )
    errs = _errors(ir, registry)
    assert not any("never used" in d.message for d in errs)


def test_bare_node_while_rejected(registry) -> None:
    # `while: ${c}` is a bare node reference (no field) → resolves to the whole
    # output dict, always truthy. It is rejected by the GENERIC template validator
    # ("this is a node ID — use ${c.output_key}"), so no loop-specific check is
    # needed. Pin that it is rejected and that the guidance points at the fix.
    errs = _errors(_shell_loop("${c}"), registry)
    assert errs  # bare node `while:` must not pass validation
    assert any("node ID" in d.message or "output_key" in d.message for d in errs)


def test_bare_input_while_not_rejected(registry) -> None:
    # A bare reference to a declared INPUT (not a node) is a legitimate typed
    # value — it must NOT be rejected. (CLI-verified: a `type: integer` input with
    # a default validates clean as a `while:` source.)
    ir = _ir(
        [
            {
                "id": "c",
                "type": "shell",
                "params": {"command": "echo hi"},
                "loop": {"while": "${threshold}", "max_iterations": 3},
            }
        ],
        inputs={"threshold": {"type": "integer", "required": False, "default": 1}},
    )
    # No LOOP-CONDITION rejection fires (any unrelated "input not provided" noise
    # from the no-fill-defaults validate path is not our concern here; the CLI,
    # which fills defaults, validates this workflow clean).
    loop_msgs = ("node ID", "output_key", "a string", "operator", "mutually exclusive", "visit cap")
    assert not any(kw in d.message for d in _errors(ir, registry) for kw in loop_msgs)


def test_batch_and_loop_rejected_on_validate_path(registry) -> None:
    # Mutual exclusion must be caught by the validator (save / --validate-only),
    # not only by the compiler at run time.
    ir = _ir([
        {
            "id": "c",
            "type": "shell",
            "params": {"command": "echo hi"},
            "batch": {"items": ["a", "b"], "as": "item"},
            "loop": {"while": "${c.exit_code}", "max_iterations": 3},
        }
    ])
    errs = _errors(ir, registry)
    assert any("mutually exclusive" in d.message for d in errs)


def test_literal_max_iterations_over_cap_rejected_on_validate_path(registry) -> None:
    # A literal max_iterations over the hard visit cap must fail validation, not
    # only at compile time. Default MAX_NODE_VISITS is 100.
    errs = _errors(_shell_loop("${c.exit_code}", max_it=999), registry)
    assert any("hard visit cap" in d.message for d in errs)


def test_until_known_string_rejected_with_until_path_and_message(registry) -> None:
    ir = _ir([
        {
            "id": "c",
            "type": "shell",
            "params": {"command": "echo hi"},
            "loop": {"until": "${c.stdout}", "max_iterations": 3},
        }
    ])
    errs = _errors(ir, registry)
    assert any("`loop: until:`" in d.message for d in errs)
    assert any(d.context and d.context.get("path") == "nodes[id=c].loop.until" for d in errs)


def test_while_and_until_both_rejected_on_validate_path(registry) -> None:
    ir = _ir([
        {
            "id": "c",
            "type": "shell",
            "params": {"command": "echo hi"},
            "loop": {"while": "${c.exit_code}", "until": "${c.exit_code}", "max_iterations": 3},
        }
    ])
    errs = _errors(ir, registry)
    assert sum("exactly one" in d.message for d in errs) == 1


def test_neither_while_nor_until_rejected_on_validate_path(registry) -> None:
    ir = _ir([
        {
            "id": "c",
            "type": "shell",
            "params": {"command": "echo hi"},
            "loop": {"max_iterations": 3},
        }
    ])
    errs = _errors(ir, registry)
    assert any("exactly one" in d.message for d in errs)


def test_carry_key_without_seed_rejected(registry) -> None:
    ir = _ir([
        {
            "id": "c",
            "type": "code",
            "params": {
                "inputs": {},
                "code": 'result: dict = {"next_state": "x", "more": False}',
            },
            "loop": {"carry": {"state": "${c.result}"}, "while": "${c.result.more}", "max_iterations": 3},
        }
    ])
    errs = _errors(ir, registry)
    assert any("does not seed" in d.message for d in errs)


def test_carry_value_must_self_reference_loop_node(registry) -> None:
    ir = _ir([
        {
            "id": "other",
            "type": "code",
            "params": {"code": 'result: str = "x"'},
        },
        {
            "id": "c",
            "type": "code",
            "params": {
                "inputs": {"state": "seed"},
                "code": 'state: str\nresult: dict = {"next_state": state, "more": False}',
            },
            "loop": {"carry": {"state": "${other.result}"}, "while": "${c.result.more}", "max_iterations": 3},
        },
    ])
    errs = _errors(ir, registry)
    assert any("must reference this loop node" in d.message for d in errs)


def test_bare_carry_alias_rejected_as_self_reference_error(registry) -> None:
    ir = _ir([
        {
            "id": "c",
            "type": "code",
            "params": {
                "inputs": {"state": "seed"},
                "code": 'state: str\nresult: dict = {"next_state": state, "more": False}',
            },
            "loop": {"carry": {"state": "${result}"}, "while": "${c.result.more}", "max_iterations": 3},
        }
    ])
    errs = _errors(ir, registry)
    assert any("must reference this loop node" in d.message for d in errs)
    assert not any("does not declare output" in d.message for d in errs)


def test_typoed_carry_output_rejected_for_precise_code_output(registry) -> None:
    ir = _ir([
        {
            "id": "c",
            "type": "code",
            "params": {
                "inputs": {"state": "seed"},
                "code": 'state: str\nresult: dict = {"next_state": state, "more": False}',
            },
            "loop": {"carry": {"state": "${c.missing}"}, "while": "${c.result.more}", "max_iterations": 3},
        }
    ])
    errs = _errors(ir, registry)
    assert any("does not declare output 'missing'" in d.message for d in errs)


def test_carry_typo_diagnostic_offers_did_you_mean_and_available_outputs(registry) -> None:
    """A typo'd carry output names the close match (`reslt` → `result`) AND lists the loop
    node's declared outputs — the validator already has both, so surface them."""
    ir = _ir([
        {
            "id": "c",
            "type": "code",
            "params": {
                "inputs": {"state": "seed"},
                "code": 'state: str\nresult: dict = {"next_state": state, "more": False}',
            },
            "loop": {"carry": {"state": "${c.reslt}"}, "while": "${c.result.more}", "max_iterations": 3},
        }
    ])
    errs = _errors(ir, registry)
    typo = next(d for d in errs if "does not declare output 'reslt'" in d.message)
    assert "result" in typo.context.get("similar_names", [])
    assert "result" in typo.context.get("available_fields", [])
    assert typo.context.get("available_fields_label") == "outputs"


def test_empty_loop_block_rejected_as_missing_polarity(registry) -> None:
    """`loop: {}` must error (missing polarity), not be silently ignored (the `is None` vs
    `not` distinction this task deliberately changed)."""
    ir = _ir([
        {
            "id": "c",
            "type": "code",
            "params": {"code": 'result: dict = {"more": False}'},
            "loop": {},
        }
    ])
    errs = _errors(ir, registry)
    assert any("exactly one of `while:` or `until:`" in d.message for d in errs)


def test_shell_carry_key_not_referenced_warns(registry) -> None:
    ir = _ir([
        {
            "id": "c",
            "type": "shell",
            "params": {
                "inputs": {"state": "seed"},
                "command": "echo hi",
            },
            "loop": {"carry": {"state": "${c.exit_code}"}, "while": "${c.exit_code}", "max_iterations": 3},
        }
    ])
    diagnostics = _diagnostics(ir, registry)
    assert any(d.severity == Severity.WARNING and "carries input 'state'" in d.message for d in diagnostics)


def test_coalesce_carry_with_literal_fallback_not_falsely_rejected(registry) -> None:
    """A coalesce carry with a literal fallback (`${c.result ?? "start"}`) must NOT be
    rejected: the first operand is a real output and the literal isn't a typo. The
    pre-fix parser read the output name as `result ?? "start"` and hard-errored on it.
    """
    ir = _ir([
        {
            "id": "c",
            "type": "code",
            "params": {
                "inputs": {"state": "seed"},
                "code": 'state: str\nresult: dict = {"next_state": state, "more": False}',
            },
            "loop": {"carry": {"state": '${c.result ?? "start"}'}, "while": "${c.result.more}", "max_iterations": 3},
        }
    ])
    errs = _errors(ir, registry)
    assert not any("does not declare output" in d.message for d in errs), [d.message for d in errs]


def test_coalesce_carry_typo_in_operand_still_caught(registry) -> None:
    """Operand-by-operand checking must still catch a typo'd output inside a coalesce."""
    ir = _ir([
        {
            "id": "c",
            "type": "code",
            "params": {
                "inputs": {"state": "seed"},
                "code": 'state: str\nresult: dict = {"next_state": state, "more": False}',
            },
            "loop": {
                "carry": {"state": "${c.result ?? c.missing}"},
                "while": "${c.result.more}",
                "max_iterations": 3,
            },
        }
    ])
    errs = _errors(ir, registry)
    assert any("does not declare output 'missing'" in d.message for d in errs)


def test_shell_carry_key_referenced_via_nested_path_no_warning(registry) -> None:
    """A carried key used via a NESTED path (`${state.summary}`) is referenced — the old
    exact `${state}` substring check false-positived on this and warned spuriously.
    """
    ir = _ir([
        {
            "id": "c",
            "type": "shell",
            "params": {
                "inputs": {"state": "seed"},
                "command": "echo ${state.summary}",
            },
            "loop": {"carry": {"state": "${c.stdout}"}, "while": "${c.exit_code}", "max_iterations": 3},
        }
    ])
    diagnostics = _diagnostics(ir, registry)
    assert not any("carries input 'state'" in d.message for d in diagnostics), [d.message for d in diagnostics]


def test_carry_literal_coalesce_fallback_warns(registry) -> None:
    """A LITERAL coalesce fallback in carry (`${c.result.next ?? "x"}`) always resolves, so it
    silently re-seeds when the body omits the output — defeating the loud carry guard. Warn
    (not error: a literal fallback may be intentional).
    """
    ir = _ir([
        {
            "id": "c",
            "type": "code",
            "params": {
                "inputs": {"state": "seed"},
                "code": 'state: str\nresult: dict = {"next": state, "more": False}',
            },
            "loop": {
                "carry": {"state": '${c.result.next ?? "x"}'},
                "while": "${c.result.more}",
                "max_iterations": 3,
            },
        }
    ])
    diagnostics = _diagnostics(ir, registry)
    assert any(d.severity == Severity.WARNING and "literal fallback" in d.message for d in diagnostics), [
        d.message for d in diagnostics
    ]
    # It is a WARNING, never an ERROR (the workflow still validates).
    assert not any("literal fallback" in d.message for d in _errors(ir, registry))


def test_carry_two_output_coalesce_does_not_warn_literal_fallback(registry) -> None:
    """A coalesce between two real outputs (`${c.result.a ?? c.result.b}`) has no literal
    operand — the silent-re-seed warning must NOT fire on it."""
    ir = _ir([
        {
            "id": "c",
            "type": "code",
            "params": {
                "inputs": {"state": "seed"},
                "code": 'state: str\nresult: dict = {"a": state, "b": state, "more": False}',
            },
            "loop": {
                "carry": {"state": "${c.result.a ?? c.result.b}"},
                "while": "${c.result.more}",
                "max_iterations": 3,
            },
        }
    ])
    diagnostics = _diagnostics(ir, registry)
    assert not any("literal fallback" in d.message for d in diagnostics), [d.message for d in diagnostics]
