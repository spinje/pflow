"""Tests for PythonCodeNode — behavioral tests for the code node.

Organized by what matters to users and downstream consumers, not by
internal implementation structure (prep/exec/post).
"""

import pytest

from pflow.nodes.python.python_code import (
    PythonCodeNode,
    _extract_error_location,
    _get_inner_optional_type,
    _get_outer_type,
    _is_optional_type,
    extract_optional_input_keys,
)


def run_code_node(shared: dict, **params) -> str:
    """Helper: create node, set params, run, return action string."""
    node = PythonCodeNode()
    node.set_params(params)
    return node.run(shared)


# ======================================================================
# Core value: native objects in, structured result out
# ======================================================================


class TestNativeObjectExecution:
    """The whole point of this node: native Python objects, no serialization."""

    def test_single_input_transformation(self):
        """Single input variable is accessible and produces correct result."""
        shared: dict = {}
        run_code_node(
            shared,
            code="count: int\nresult: int = count * 2",
            inputs={"count": 5},
        )
        assert shared["result"] == 10

    def test_multiple_inputs(self):
        """Multiple inputs are all injected into the namespace."""
        shared: dict = {}
        run_code_node(
            shared,
            code="a: int\nb: int\nresult: int = a + b",
            inputs={"a": 10, "b": 20},
        )
        assert shared["result"] == 30

    def test_dict_result_with_structured_data(self):
        """Dict result — the primary use case for downstream field access."""
        shared: dict = {}
        run_code_node(
            shared,
            code=(
                "items: list\n"
                "\n"
                "result: dict = {\n"
                '    "count": len(items),\n'
                '    "first": items[0],\n'
                '    "last": items[-1],\n'
                "}"
            ),
            inputs={"items": ["a", "b", "c"]},
        )
        assert shared["result"] == {"count": 3, "first": "a", "last": "c"}

    def test_list_filtering_realistic_scenario(self):
        """Realistic data transformation: filter + transform."""
        shared: dict = {}
        run_code_node(
            shared,
            code=("data: list\nthreshold: int\n\nresult: list = [x for x in data if x > threshold]"),
            inputs={"data": [1, 5, 10, 15, 3, 8], "threshold": 7},
        )
        assert shared["result"] == [10, 15, 8]

    def test_no_inputs_pure_computation(self):
        """Code with no inputs — pure computation is a valid pattern."""
        shared: dict = {}
        run_code_node(
            shared,
            code="result: list = list(range(5))",
            inputs={},
        )
        assert shared["result"] == [0, 1, 2, 3, 4]

    def test_imports_work(self):
        """Standard library imports execute correctly."""
        shared: dict = {}
        run_code_node(
            shared,
            code='import json\nresult: str = json.dumps({"key": 1})',
            inputs={},
        )
        assert shared["result"] == '{"key": 1}'

    def test_none_input_fails_type_check(self):
        """None input value fails type validation — catches upstream issues early."""
        shared: dict = {}
        with pytest.raises(TypeError, match=r"data.*expects dict.*received NoneType"):
            run_code_node(
                shared,
                code="data: dict\nresult: str = 'done'",
                inputs={"data": None},
            )

    def test_input_mutation_affects_original(self):
        """Mutating an input list in code modifies the original object.

        This is expected behavior (in-process exec, same memory).
        Users should be aware inputs are passed by reference, not copied.
        """
        original_list = [1, 2, 3]
        shared: dict = {}
        run_code_node(
            shared,
            code="data: list\ndata.append(4)\nresult: list = data",
            inputs={"data": original_list},
        )
        assert shared["result"] == [1, 2, 3, 4]
        assert original_list == [1, 2, 3, 4]  # mutated in-place


# ======================================================================
# Type annotation contract (required for Task 107 markdown workflows)
# ======================================================================


class TestTypeAnnotationContract:
    """Type annotations are required — strategic for IDE support in Task 107."""

    def test_missing_input_annotation_rejected(self):
        """Input without type annotation in code is caught before execution."""
        shared: dict = {}
        with pytest.raises(ValueError, match=r"missing type annotation.*data"):
            run_code_node(
                shared,
                code="result: int = 42",
                inputs={"data": [1, 2]},
            )

    def test_missing_result_annotation_rejected(self):
        """Code without result or next type annotation is rejected."""
        shared: dict = {}
        with pytest.raises(ValueError, match="result type annotation"):
            run_code_node(
                shared,
                code="x: int = 5",
                inputs={},
            )

    def test_input_type_mismatch_caught(self):
        """Wrong input type caught in prep with actionable error."""
        shared: dict = {}
        with pytest.raises(TypeError, match=r"data.*expects list.*received dict"):
            run_code_node(
                shared,
                code="data: list\nresult: int = 0",
                inputs={"data": {"a": 1}},
            )

    def test_type_mismatch_error_includes_suggestion(self):
        """Type error suggests the correct type annotation."""
        shared: dict = {}
        with pytest.raises(TypeError) as exc_info:
            run_code_node(
                shared,
                code="data: str\nresult: int = 0",
                inputs={"data": [1, 2, 3]},
            )
        error = str(exc_info.value)
        assert "Suggestions:" in error
        assert "data: list" in error

    def test_generic_type_validates_outer_only(self):
        """list[dict] checks isinstance(value, list), ignores element types.

        This is a design decision: deep validation deferred to Task 107.
        """
        shared: dict = {}
        # list[dict] with list of ints — passes because only outer type checked
        run_code_node(
            shared,
            code="data: list[dict]\nresult: int = len(data)",
            inputs={"data": [1, 2, 3]},  # list of int, not dict — still passes
        )
        assert shared["result"] == 3

    def test_result_type_mismatch_caught_in_post(self):
        """Result type checked after execution — catches code bugs."""
        shared: dict = {}
        action = run_code_node(
            shared,
            code='result: int = "text"',
            inputs={},
        )
        assert action == "error"
        assert "declared as int but code returned str" in shared["error"]
        assert "Suggestions:" in shared["error"]

    def test_bool_passes_as_int(self):
        """bool is subclass of int in Python — passes isinstance(True, int).

        This is Python semantics, not a bug. Document the behavior.
        """
        shared: dict = {}
        action = run_code_node(
            shared,
            code="flag: int\nresult: int = flag + 1",
            inputs={"flag": True},
        )
        assert action == "default"
        assert shared["result"] == 2  # True + 1 = 2

    def test_int_passes_as_float(self):
        """int is accepted where float is declared — TYPE_MAP uses (int, float)."""
        shared: dict = {}
        action = run_code_node(
            shared,
            code="val: float\nresult: float = val * 2.5",
            inputs={"val": 4},
        )
        assert action == "default"
        assert shared["result"] == 10.0

    def test_unknown_type_annotation_skips_check(self):
        """Type annotations not in TYPE_MAP skip isinstance — no crash.

        Uses `object` (a real builtin) to avoid NameError during exec.
        Note: annotations like `DataFrame` would need an import to not fail
        at exec time, since Python evaluates annotations eagerly in exec().
        """
        shared: dict = {}
        action = run_code_node(
            shared,
            code="data: object\nresult: int = 42",
            inputs={"data": {"col": [1, 2]}},  # dict, but object not in TYPE_MAP
        )
        assert action == "default"
        assert shared["result"] == 42


# ======================================================================
# Output capture: stdout, stderr, result
# ======================================================================


class TestOutputCapture:
    """Verify stdout/stderr capture and result extraction."""

    def test_stdout_captured(self):
        """print() output available in shared['stdout']."""
        shared: dict = {}
        run_code_node(
            shared,
            code='print("hello")\nresult: str = "done"',
            inputs={},
        )
        assert shared["stdout"] == "hello\n"

    def test_stderr_captured(self):
        """stderr writes available in shared['stderr']."""
        shared: dict = {}
        run_code_node(
            shared,
            code='import sys\nsys.stderr.write("warn")\nresult: str = "done"',
            inputs={},
        )
        assert shared["stderr"] == "warn"

    def test_missing_result_assignment(self):
        """Code that declares result type but never assigns it."""
        shared: dict = {}
        action = run_code_node(
            shared,
            code="result: int\nx = 5",
            inputs={},
        )
        assert action == "error"
        assert "must set 'result' variable" in shared["error"]


# ======================================================================
# Safety: timeout, error handling, workflow routing
# ======================================================================


class TestSafetyAndErrors:
    """Timeout enforcement and error handling quality."""

    def test_timeout_stops_long_running_code(self):
        """Infinite/slow code doesn't hang the workflow."""
        shared: dict = {}
        # Sleep BEFORE result assignment so if timeout fails the result is also missing.
        # Use 1s sleep vs 0.05s timeout (20x margin) for CI reliability.
        # The zombie sleep thread self-terminates after 1s.
        #
        # PERF: Keep timeout small (<0.1s). With pytest-xdist, a single 0.5s test
        # caused total suite time to jump from 7s to 14s due to worker scheduling.
        action = run_code_node(
            shared,
            code="import time\ntime.sleep(1)\nresult: int = 0",
            timeout=0.05,
            inputs={},
        )
        assert action == "error"
        assert "timed out" in shared["error"]

    def test_name_error_identifies_variable(self):
        """NameError message includes the undefined variable name."""
        shared: dict = {}
        action = run_code_node(
            shared,
            code="result: int = undefined_var",
            inputs={},
        )
        assert action == "error"
        assert "undefined_var" in shared["error"]

    def test_import_error_identifies_module(self):
        """ImportError message includes the missing module name."""
        shared: dict = {}
        action = run_code_node(
            shared,
            code="import nonexistent_module_xyz\nresult: int = 0",
            inputs={},
        )
        assert action == "error"
        assert "nonexistent_module_xyz" in shared["error"]
        assert "not found" in shared["error"]

    def test_syntax_error_includes_line_info(self):
        """SyntaxError surfaces line number for debugging."""
        shared: dict = {}
        with pytest.raises(SyntaxError) as exc_info:
            run_code_node(
                shared,
                code="x: int = 1\nresult = [",
                inputs={},
            )
        assert exc_info.value.lineno is not None

    def test_runtime_error_includes_line_number(self):
        """Runtime errors include the line number and source for debugging."""
        shared: dict = {}
        action = run_code_node(
            shared,
            code="x: int = 1\ny: int = 0\nresult: int = x / y",
            inputs={},
        )
        assert action == "error"
        assert "ZeroDivisionError" in shared["error"]
        assert "Location: line 3 in code block" in shared["error"]
        assert "Source: result: int = x / y" in shared["error"]
        assert "Suggestions:" in shared["error"]

    def test_success_returns_default_action(self):
        """Successful execution routes to default action."""
        shared: dict = {}
        action = run_code_node(
            shared,
            code="result: int = 42",
            inputs={},
        )
        assert action == "default"
        assert shared["result"] == 42


# ======================================================================
# Next variable routing (dynamic action from code)
# ======================================================================


class TestNextVariableRouting:
    """Test dynamic routing via the `next` variable in code.

    Code can set ``next: str = "target"`` to control which node runs after
    this one. When ``next`` is set, it becomes the action returned by post().
    The ``result`` annotation is optional when ``next`` is declared.
    """

    def test_next_set_returns_as_action(self):
        """Setting next variable routes to the specified action."""
        shared: dict = {}
        action = run_code_node(
            shared,
            code='next: str = "priority"\nresult: int = 42',
            inputs={},
        )
        assert action == "priority"
        assert shared["result"] == 42

    def test_next_not_set_returns_default(self):
        """Without next variable, action is 'default' as before."""
        shared: dict = {}
        action = run_code_node(
            shared,
            code="result: int = 42",
            inputs={},
        )
        assert action == "default"

    def test_next_without_result_works(self):
        """Code with only next (no result annotation) is valid for pure routing."""
        shared: dict = {}
        action = run_code_node(
            shared,
            code='next: str = "skip"',
            inputs={},
        )
        assert action == "skip"
        assert "result" not in shared

    def test_next_conditionally_set(self):
        """Next can be set conditionally based on input data."""
        code = 'flag: bool\nresult: int = 0\nif flag:\n    next: str = "fast"\nelse:\n    next: str = "slow"'

        # Branch: flag=True -> "fast"
        shared_true: dict = {}
        action_true = run_code_node(shared_true, code=code, inputs={"flag": True})
        assert action_true == "fast"

        # Branch: flag=False -> "slow"
        shared_false: dict = {}
        action_false = run_code_node(shared_false, code=code, inputs={"flag": False})
        assert action_false == "slow"

    def test_next_non_string_returns_error(self):
        """Non-string next value is caught in post with actionable error."""
        shared: dict = {}
        action = run_code_node(
            shared,
            code="result: int = 1\nnext = 42",
            inputs={},
        )
        assert action == "error"
        assert "next" in shared["error"]
        assert "string" in shared["error"].lower()

    def test_next_empty_string_returns_error(self):
        """Empty string next value is rejected."""
        shared: dict = {}
        action = run_code_node(
            shared,
            code='next: str = ""',
            inputs={},
        )
        assert action == "error"
        assert "empty" in shared["error"].lower()

    def test_error_overrides_next(self):
        """Runtime error takes precedence over next variable."""
        shared: dict = {}
        action = run_code_node(
            shared,
            code='next: str = "target"\nraise ValueError("boom")',
            inputs={},
        )
        assert action == "error"
        assert "boom" in shared["error"]

    def test_no_result_and_no_next_rejected(self):
        """Code without either result or next annotation is rejected in prep."""
        shared: dict = {}
        with pytest.raises(ValueError, match="result type annotation"):
            run_code_node(
                shared,
                code="x: int = 5",
                inputs={},
            )

    def test_next_annotation_wrong_type_rejected(self):
        """Next annotated as non-str type is rejected in prep."""
        shared: dict = {}
        with pytest.raises(ValueError, match="'next' must be annotated as str"):
            run_code_node(
                shared,
                code="next: int = 5\nresult: int = 1",
                inputs={},
            )

    def test_next_not_stored_in_shared(self):
        """Next is used for routing only -- not stored in shared store."""
        shared: dict = {}
        action = run_code_node(
            shared,
            code='next: str = "target"\nresult: int = 42',
            inputs={},
        )
        assert action == "target"
        assert shared["result"] == 42
        assert "next" not in shared

    def test_result_type_mismatch_still_errors_with_next(self):
        """Result type mismatch is caught even when next is set."""
        shared: dict = {}
        action = run_code_node(
            shared,
            code='result: int = "string"\nnext: str = "target"',
            inputs={},
        )
        assert action == "error"
        assert "declared as int but code returned str" in shared["error"]


# ======================================================================
# Edge cases and parameter validation
# ======================================================================


class TestEdgeCases:
    """Boundary conditions and parameter validation."""

    def test_empty_code_rejected(self):
        shared: dict = {}
        with pytest.raises(ValueError, match="Missing required 'code' parameter"):
            run_code_node(shared, code="", inputs={})

    def test_whitespace_only_code_rejected(self):
        shared: dict = {}
        with pytest.raises(ValueError, match="Missing required 'code' parameter"):
            run_code_node(shared, code="   \n  \n  ", inputs={})

    def test_negative_timeout_rejected(self):
        shared: dict = {}
        with pytest.raises(ValueError, match="positive number"):
            run_code_node(shared, code="result: int = 1", timeout=-5)

    def test_requires_field_accepted_without_validation(self):
        """requires is documentation-only — doesn't crash even if packages missing."""
        shared: dict = {}
        action = run_code_node(
            shared,
            code="result: str = 'ok'",
            requires=["pandas", "numpy"],
            inputs={},
        )
        assert action == "default"


# ======================================================================
# Integration: compile + template resolution + execution pipeline
# ======================================================================


class TestWorkflowIntegration:
    """Verify the code node works through the full compiler/executor pipeline.

    These tests exercise the integration seams that unit tests can't reach:
    1. Registry scanner discovers PythonCodeNode as type "code"
    2. Compiler instantiates and wraps it (template + namespace wrappers)
    3. Template resolution resolves ${...} INSIDE the inputs dict
    4. Namespaced shared store output is accessible to downstream nodes
    """

    def test_code_node_in_compiled_workflow(self):
        """Echo → Code workflow: template resolution through inputs dict.

        This is the critical integration path. The inputs dict contains
        ${source.echo} which must be resolved by the TemplateAwareNodeWrapper
        before the code node's prep() sees it as a native Python object.
        """
        from pflow.runtime import compile_ir_to_flow
        from tests.shared.registry_utils import ensure_test_registry

        registry = ensure_test_registry()

        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "source",
                    "type": "echo",
                    "params": {
                        "data": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
                    },
                },
                {
                    "id": "transform",
                    "type": "code",
                    "params": {
                        "inputs": {
                            "data": "${source.data}",
                            "limit": 5,
                        },
                        "code": "data: list\nlimit: int\n\nresult: list = data[:limit]",
                    },
                },
            ],
            "edges": [{"from": "source", "to": "transform"}],
        }

        flow = compile_ir_to_flow(workflow_ir, registry, validate=False)
        shared: dict = {}
        flow.run(shared)

        # Code node output is namespaced under "transform"
        assert shared["transform"]["result"] == [1, 2, 3, 4, 5]
        assert shared["transform"]["stdout"] == ""


# ======================================================================
# Workflow line reference in error messages (source line tracking)
# ======================================================================


class TestErrorLocationWorkflowLine:
    """Verify _extract_error_location appends workflow file line references.

    When a code node errors at runtime and _code_source_line is set, the
    error location string should include both the line within the code
    block AND the corresponding line in the .pflow.md file. This lets
    users jump straight to the right place in their workflow file.

    Formula: workflow_line = code_source_line + lineno - 1
    (code_source_line is 1-based line where code content starts in
    the .pflow.md file; lineno is 1-based line within the code block).
    """

    def test_extract_error_location_includes_workflow_line_when_source_set(self):
        """With code_source_line > 0, the location string includes (workflow line N).

        Error on line 3 of code that starts at workflow line 50
        should produce workflow line 52 (50 + 3 - 1).
        """
        code = "x = 1\ny = 2\nraise ValueError('boom')"
        compiled = compile(code, "<code>", "exec")
        try:
            exec(compiled)  # noqa: S102
            pytest.fail("Expected ValueError was not raised")
        except ValueError as exc:
            location = _extract_error_location(exc, code, code_source_line=50)

        assert "Location: line 52 (line 3 in code block)" in location
        assert "Source: raise ValueError" in location

    def test_extract_error_location_omits_workflow_line_when_source_zero(self):
        """With code_source_line=0 (the default), no workflow line reference.

        This preserves backward compatibility for code nodes not loaded
        from .pflow.md files (e.g., passed directly via IR dict).
        """
        code = "x = 1\ny = 2\nraise ValueError('boom')"
        compiled = compile(code, "<code>", "exec")
        try:
            exec(compiled)  # noqa: S102
            pytest.fail("Expected ValueError was not raised")
        except ValueError as exc:
            location = _extract_error_location(exc, code, code_source_line=0)

        assert "Location: line 3 in code block" in location
        assert "Source: raise ValueError" in location


# ======================================================================
# Optional type system support
# ======================================================================


class TestOptionalTypeSupport:
    """Tests for Optional type annotation parsing and type checking.

    Covers _is_optional_type, _get_inner_optional_type, _get_outer_type
    (optional decomposition), _check_input_types (optional acceptance),
    extract_optional_input_keys, and typing availability in exec namespace.
    """

    # --- _is_optional_type ---

    def test_is_optional_type_str_pipe_none(self):
        """'str | None' is recognized as optional."""
        assert _is_optional_type("str | None") is True

    def test_is_optional_type_optional_str(self):
        """'Optional[str]' is recognized as optional."""
        assert _is_optional_type("Optional[str]") is True

    def test_is_optional_type_none_pipe_str(self):
        """'None | str' is recognized as optional."""
        assert _is_optional_type("None | str") is True

    def test_is_optional_type_plain_str(self):
        """'str' is NOT optional."""
        assert _is_optional_type("str") is False

    def test_is_optional_type_list_str_pipe_none(self):
        """'list[str] | None' is recognized as optional."""
        assert _is_optional_type("list[str] | None") is True

    # --- _get_inner_optional_type ---

    def test_get_inner_optional_type_str_pipe_none(self):
        """'str | None' extracts inner type 'str'."""
        assert _get_inner_optional_type("str | None") == "str"

    def test_get_inner_optional_type_optional_str(self):
        """'Optional[str]' extracts inner type 'str'."""
        assert _get_inner_optional_type("Optional[str]") == "str"

    def test_get_inner_optional_type_none_pipe_str(self):
        """'None | str' extracts inner type 'str'."""
        assert _get_inner_optional_type("None | str") == "str"

    def test_get_inner_optional_type_list_pipe_none(self):
        """'list[str] | None' extracts inner type 'list[str]'."""
        assert _get_inner_optional_type("list[str] | None") == "list[str]"

    def test_get_inner_optional_type_plain_str(self):
        """'str' returns None (not optional)."""
        assert _get_inner_optional_type("str") is None

    # --- _get_outer_type (optional decomposition) ---

    def test_get_outer_type_str_pipe_none(self):
        """'str | None' resolves to (str, NoneType)."""
        result = _get_outer_type("str | None")
        assert result == (str, type(None))

    def test_get_outer_type_optional_list(self):
        """'Optional[list]' resolves to (list, NoneType)."""
        result = _get_outer_type("Optional[list]")
        assert result == (list, type(None))

    def test_get_outer_type_float_pipe_none(self):
        """'float | None' resolves to (int, float, NoneType) since float maps to (int, float)."""
        result = _get_outer_type("float | None")
        assert result == (int, float, type(None))

    def test_get_outer_type_unchanged_for_plain(self):
        """'str' resolves to str (unchanged, non-optional behavior)."""
        result = _get_outer_type("str")
        assert result is str

    # --- _check_input_types (optional type acceptance) ---

    def test_check_input_types_accepts_none_for_optional(self):
        """None is accepted for 'str | None' annotation."""
        # Should not raise
        PythonCodeNode._check_input_types({"x": None}, {"x": "str | None"})

    def test_check_input_types_accepts_value_for_optional(self):
        """A string value is accepted for 'str | None' annotation."""
        # Should not raise
        PythonCodeNode._check_input_types({"x": "hello"}, {"x": "str | None"})

    def test_check_input_types_rejects_none_for_non_optional(self):
        """None is rejected for non-optional 'str' annotation."""
        with pytest.raises(TypeError, match=r"x.*expects str.*received NoneType"):
            PythonCodeNode._check_input_types({"x": None}, {"x": "str"})

    def test_check_input_types_rejects_wrong_type_for_optional(self):
        """Wrong type (int) is rejected even when annotation is optional."""
        with pytest.raises(TypeError, match=r"x.*expects str \| None.*received int"):
            PythonCodeNode._check_input_types({"x": 42}, {"x": "str | None"})

    # --- extract_optional_input_keys ---

    def test_extract_optional_input_keys(self):
        """Both optional inputs are returned when both are annotated as optional."""
        code = "high: str | None\nlow: str | None\nresult: str"
        result = extract_optional_input_keys(code, {"high", "low"})
        assert result == {"high", "low"}

    def test_extract_optional_input_keys_mixed(self):
        """Only the optional input is returned when annotations are mixed."""
        code = "high: str | None\nlow: str\nresult: str"
        result = extract_optional_input_keys(code, {"high", "low"})
        assert result == {"high"}

    def test_extract_optional_input_keys_syntax_error(self):
        """Syntax error in code returns empty set (graceful fallback)."""
        result = extract_optional_input_keys("invalid python ~~~", {"x"})
        assert result == set()

    # --- typing module available in exec namespace ---

    def test_typing_available_in_namespace(self):
        """Code using Optional[str] from typing module executes without NameError."""
        shared: dict = {}
        action = run_code_node(
            shared,
            code='from typing import Optional\nx: Optional[str] = "hello"\nresult: str = x',
            inputs={},
        )
        assert action == "default"
        assert shared["result"] == "hello"

    # --- typing.Optional[T] form ---

    def test_is_optional_type_typing_dot_optional(self):
        """'typing.Optional[str]' is recognized as optional."""
        assert _is_optional_type("typing.Optional[str]") is True

    def test_get_inner_optional_type_typing_dot_optional(self):
        """'typing.Optional[str]' extracts inner type 'str'."""
        assert _get_inner_optional_type("typing.Optional[str]") == "str"

    def test_get_inner_optional_type_typing_dot_optional_list(self):
        """'typing.Optional[list[str]]' extracts inner type 'list[str]'."""
        assert _get_inner_optional_type("typing.Optional[list[str]]") == "list[str]"

    def test_get_outer_type_typing_dot_optional(self):
        """'typing.Optional[str]' resolves to (str, NoneType)."""
        result = _get_outer_type("typing.Optional[str]")
        assert result == (str, type(None))

    def test_extract_optional_input_keys_typing_dot_optional(self):
        """typing.Optional[str] annotation is detected by extract_optional_input_keys."""
        code = "x: typing.Optional[str]\nresult: str = x or 'default'"
        result = extract_optional_input_keys(code, {"x"})
        assert result == {"x"}
