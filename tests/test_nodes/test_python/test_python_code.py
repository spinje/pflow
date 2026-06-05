"""Tests for PythonCodeNode — behavioral tests for the code node.

Organized by what matters to users and downstream consumers, not by
internal implementation structure (prep/exec/post).
"""

import pytest

from pflow.nodes.file.exceptions import NonRetriableError
from pflow.nodes.python.python_code import (
    PythonCodeNode,
    _extract_error_location,
    _get_inner_optional_type,
    _get_outer_type,
    _get_outer_type_name,
    _is_optional_type,
    extract_code_annotation_type,
    extract_code_assigned_names,
    extract_code_load_references,
    extract_optional_input_keys,
    extract_top_level_annotations,
    s1_type_to_python_display,
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

    def test_forward_reference_annotation_enforced_at_runtime(self):
        """Forward-ref `x: "dict"` must enforce isinstance, not silently accept.

        Pre-fix: `_get_outer_type("'dict'")` returned None (lookup miss on
        quoted string), runtime skipped the isinstance check, wrong-typed
        values passed through. Post-fix: forward refs are unwrapped and
        enforced identically to bare annotations.
        """
        shared: dict = {}
        with pytest.raises(TypeError, match=r"x.*expects .*dict.*received list"):
            run_code_node(
                shared,
                code='x: "dict"\nresult: str = str(x)',
                inputs={"x": [1, 2, 3]},
            )

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

    def test_union_in_annotation_rejected_with_pipe_syntax_hint(self):
        """Union in an annotation should be rejected at prep with a PEP 604 hint.

        AST-walk detection runs at validation time, so the opinionated guidance
        reaches the user consistently — including Python 3.14+ where PEP 649
        defers annotation evaluation and the runtime NameError never fires.
        """
        shared: dict = {}
        with pytest.raises(NonRetriableError) as exc_info:
            run_code_node(
                shared,
                code="x: Union[int, str] = 1\nresult: int = x",
                inputs={},
            )
        msg = str(exc_info.value)
        assert "pipe syntax" in msg
        assert "int | str" in msg
        # Opinionated: Union does NOT suggest import — modern syntax is the canonical fix.
        assert "from typing import Union" not in msg

    def test_list_in_annotation_rejected_with_lowercase_generic_hint(self):
        """List/Dict/Tuple in an annotation should be rejected at prep with a PEP 585 hint."""
        shared: dict = {}
        with pytest.raises(NonRetriableError) as exc_info:
            run_code_node(
                shared,
                code="x: List[int] = [1, 2]\nresult: int = len(x)",
                inputs={},
            )
        msg = str(exc_info.value)
        assert "list[...]" in msg or "list[str]" in msg
        assert "PEP 585" in msg
        # Opinionated: List does NOT suggest `from typing import List` — lowercase is canonical.
        assert "from typing import List" not in msg


class TestAnnotationExtractionHelper:
    """Validate the shared helper used by validate-time type checking."""

    def test_get_outer_type_name_returns_s1_canonical(self):
        assert _get_outer_type_name("list") == "array"
        assert _get_outer_type_name("dict") == "object"
        assert _get_outer_type_name("str") == "string"
        assert _get_outer_type_name("int") == "integer"
        assert _get_outer_type_name("float") == "number"
        assert _get_outer_type_name("bool") == "boolean"

    def test_get_outer_type_name_strips_generics(self):
        assert _get_outer_type_name("list[dict]") == "array"
        assert _get_outer_type_name("dict[str, int]") == "object"

    def test_get_outer_type_name_decomposes_optional(self):
        assert _get_outer_type_name("str | None") == "string"
        assert _get_outer_type_name("None | list") == "array"
        assert _get_outer_type_name("Optional[dict]") == "object"

    def test_get_outer_type_name_unknown_returns_none(self):
        assert _get_outer_type_name("Any") is None
        assert _get_outer_type_name("DataFrame") is None
        assert _get_outer_type_name("set") is None
        assert _get_outer_type_name("tuple") is None
        assert _get_outer_type_name("bytes") is None

    def test_extract_code_annotation_type_happy_path(self):
        code = "x: list\ny: dict\nresult: str = str(x)"
        assert extract_code_annotation_type(code, "x") == "array"
        assert extract_code_annotation_type(code, "y") == "object"

    def test_extract_code_annotation_type_missing_key(self):
        assert extract_code_annotation_type("x: list", "missing") is None

    def test_extract_code_annotation_type_malformed_code(self):
        assert extract_code_annotation_type("x: dict =", "x") is None

    def test_s1_to_python_display_reverses_canonical(self):
        assert s1_type_to_python_display("array") == "list"
        assert s1_type_to_python_display("object") == "dict"
        assert s1_type_to_python_display("string") == "str"
        assert s1_type_to_python_display("integer") == "int"
        assert s1_type_to_python_display("number") == "float"
        assert s1_type_to_python_display("boolean") == "bool"

    def test_s1_to_python_display_passes_through_python_names(self):
        """Already-Python names (e.g. registry-declared 'str') pass through."""
        assert s1_type_to_python_display("str") == "str"
        assert s1_type_to_python_display("list") == "list"
        assert s1_type_to_python_display("any") == "any"

    def test_s1_to_python_display_handles_unions(self):
        assert s1_type_to_python_display("array|string") == "list|str"
        assert s1_type_to_python_display("dict|str") == "dict|str"

    def test_load_references_finds_reads_in_body(self):
        code = "x: list\ny: dict\nresult: int = len(x)"
        refs = extract_code_load_references(code)
        # `x` is read; `y` is only annotated; `len` is a builtin read; `result` is Store.
        assert "x" in refs
        assert "y" not in refs
        assert "len" in refs
        assert "result" not in refs

    def test_load_references_handles_nested_scopes(self):
        code = "x: list\ndef inner():\n    return x\nresult: int = inner()"
        refs = extract_code_load_references(code)
        assert "x" in refs
        assert "inner" in refs

    def test_load_references_malformed_code_returns_empty(self):
        assert extract_code_load_references("x: dict =") == set()

    def test_assigned_names_annotated_local_with_value(self):
        # `data: list` is a bare annotation (an input) — NOT assigned.
        # `all_items: list = [...]` and `result: int = ...` carry values — assigned.
        code = "data: list\nall_items: list = [data]\nresult: int = len(all_items)"
        assert extract_code_assigned_names(code) == {"all_items", "result"}

    def test_assigned_names_plain_assignment(self):
        code = "x: int\ntotal = x + 1\nresult: int = total"
        assigned = extract_code_assigned_names(code)
        assert "total" in assigned
        assert "x" not in assigned  # bare annotation, not assigned

    def test_assigned_names_records_def_and_class_names(self):
        # The def statement binds the name at module scope (C2): removing an
        # orphan annotation on it is the right fix. Function-internal locals
        # (different scope) stay excluded.
        code = "helper: Any\ndef helper():\n    y: int = 1\n    z = 2\n    return y + z\nresult: int = helper()"
        assigned = extract_code_assigned_names(code)
        assert "helper" in assigned  # def name = module-level binding
        assert "result" in assigned
        assert "y" not in assigned  # function-local, different scope
        assert "z" not in assigned

    def test_assigned_names_records_class_name(self):
        code = "Config: Any\nclass Config:\n    pass\nresult: Any = Config"
        assert "Config" in extract_code_assigned_names(code)

    def test_assigned_names_excludes_conditional_assignment(self):
        # Assignment nested in `if` may not run -> not a safe local (C1).
        code = "items: list\nif True:\n    items = []\nresult: int = len(items)"
        assert "items" not in extract_code_assigned_names(code)

    def test_assigned_names_excludes_augmented_assignment(self):
        # `count += 1` reads before storing -> needs a prior binding (C4).
        code = "count: int\ncount += 1\nresult: int = count"
        assert "count" not in extract_code_assigned_names(code)

    def test_assigned_names_excludes_read_before_write(self):
        # `x = x[...]` reads x before binding -> removing the annotation unbinds it.
        code = "data: dict\ndata = data['x']\nresult: dict = data"
        assert "data" not in extract_code_assigned_names(code)

    def test_assigned_names_excludes_for_target(self):
        # `for x in ...` leaves x unbound when the iterable is empty.
        code = "x: int\nfor x in [1, 2, 3]:\n    pass\nresult: int = x"
        assert "x" not in extract_code_assigned_names(code)

    def test_assigned_names_malformed_code_returns_empty(self):
        assert extract_code_assigned_names("x: dict =") == set()

    def test_get_outer_type_name_unwraps_forward_ref(self):
        """Forward-ref annotations (`x: "list"`) come through as `"'list'"` via ast.unparse.

        Without unwrap, validate-time silently skips — hiding real type mismatches.
        """
        assert _get_outer_type_name("'list'") == "array"
        assert _get_outer_type_name('"dict"') == "object"
        assert _get_outer_type_name("'list[dict]'") == "array"
        # Still returns None for unknown types inside quotes.
        assert _get_outer_type_name("'DataFrame'") is None

    def test_get_outer_type_unwraps_forward_ref(self):
        """Runtime isinstance check must also see through forward-ref quotes.

        Pre-fix: `x: "dict" = [1,2,3]` silently accepted the list.
        Post-fix: runtime raises TypeError, matching the bare-annotation behavior.
        """
        assert _get_outer_type("'list'") is list
        assert _get_outer_type('"dict"') is dict
        assert _get_outer_type("'list[dict]'") is list

    def test_top_level_annotations_excludes_function_locals(self):
        """Function-local annotations must not surface at module scope."""
        code = """
def helper():
    y: int = 1
    return y

x: dict
result: int = helper()
"""
        annotations = extract_top_level_annotations(code)
        assert annotations == {"x": "dict", "result": "int"}
        assert "y" not in annotations

    def test_top_level_annotations_excludes_class_body(self):
        """Class body annotations must not surface at module scope."""
        code = """
class Config:
    timeout: int
    name: str

x: dict
"""
        annotations = extract_top_level_annotations(code)
        assert annotations == {"x": "dict"}
        assert "timeout" not in annotations
        assert "name" not in annotations

    def test_top_level_annotations_includes_if_scoped(self):
        """Non-scope structures (if/for/while) don't hide module-level annotations."""
        code = """
import os
if os.environ.get("FLAG"):
    y: int = 1
else:
    y: str = "2"

x: dict
"""
        annotations = extract_top_level_annotations(code)
        # `y` appears twice at module scope (one branch of `if`); last-write wins.
        # The important fact: `y` is included because `if` is not a scope boundary.
        assert "x" in annotations
        assert "y" in annotations

    def test_top_level_annotations_malformed_returns_empty(self):
        assert extract_top_level_annotations("x: dict =") == {}

    def test_python_to_s1_canonical_is_injective(self):
        """Reverse mapping from S1 to Python requires injectivity.

        `_S1_TO_PYTHON_DISPLAY` is built by reversing `_PYTHON_TO_S1_CANONICAL`.
        A future edit that maps two Python names to the same S1 name would
        silently drop one on the reverse. The module-load assertion guards
        against this; this test pins the invariant for explicit coverage.
        """
        from pflow.nodes.python import python_code

        forward = python_code._PYTHON_TO_S1_CANONICAL
        reverse = python_code._S1_TO_PYTHON_DISPLAY
        assert len(reverse) == len(forward), (
            f"Forward map has {len(forward)} entries, reverse has {len(reverse)} — "
            "PYTHON_ALIASES_AT_S1 must be injective for diagnostic display to round-trip"
        )

    def test_literal_in_annotation_rejected_with_import_hint(self):
        """Literal (no modern alternative) should be rejected at prep with an import hint."""
        shared: dict = {}
        with pytest.raises(NonRetriableError) as exc_info:
            run_code_node(
                shared,
                code='x: Literal["a", "b"] = "a"\nresult: str = x',
                inputs={},
            )
        assert "from typing import Literal" in str(exc_info.value)

    def test_typing_name_in_annotation_accepted_when_imported(self):
        """Typing names ARE accepted when the user explicitly imports them.

        The AST walker only rejects forgotten imports — it must not block users
        who follow the `from typing import Literal` suggestion.
        """
        shared: dict = {}
        action = run_code_node(
            shared,
            code='from typing import Literal\nx: Literal["a", "b"] = "a"\nresult: str = x',
            inputs={},
        )
        assert action == "default"
        assert shared["result"] == "a"

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
# Input type annotation syntax detection (#148)
# ======================================================================


class TestInputAnnotationSyntaxDetection:
    """Detect type annotations accidentally written in YAML input values.

    Users naturally mirror code block syntax (text: str) in YAML inputs,
    writing text: str = ${ref} instead of text: ${ref}. YAML treats this
    as a string value "str = <resolved>", silently corrupting the data.
    """

    def test_str_annotation_in_input_value_detected(self):
        """str = value pattern caught with actionable error."""
        shared: dict = {}
        with pytest.raises(ValueError, match=r"'text'.*type annotation"):
            run_code_node(
                shared,
                code="text: str\nresult: str = text.upper()",
                inputs={"text": "str = hello world"},
            )

    def test_int_annotation_in_input_value_detected(self):
        """int = value pattern caught."""
        shared: dict = {}
        with pytest.raises(ValueError, match=r"'count'.*type annotation"):
            run_code_node(
                shared,
                code="count: int\nresult: int = count * 2",
                inputs={"count": "int = 42"},
            )

    def test_list_annotation_in_input_value_detected(self):
        """list = value pattern caught."""
        shared: dict = {}
        with pytest.raises(ValueError, match=r"'data'.*type annotation"):
            run_code_node(
                shared,
                code="data: list\nresult: int = len(data)",
                inputs={"data": "list = [1, 2, 3]"},
            )

    def test_generic_type_annotation_detected(self):
        """list[dict] = value pattern caught."""
        shared: dict = {}
        with pytest.raises(ValueError, match=r"'items'.*type annotation"):
            run_code_node(
                shared,
                code="items: list[dict]\nresult: int = len(items)",
                inputs={"items": 'list[dict] = [{"a": 1}]'},
            )

    def test_dict_annotation_in_input_value_detected(self):
        """dict = value pattern caught."""
        shared: dict = {}
        with pytest.raises(ValueError, match=r"'config'.*type annotation"):
            run_code_node(
                shared,
                code="config: dict\nresult: str = 'ok'",
                inputs={"config": 'dict = {"key": "val"}'},
            )

    def test_error_message_shows_correct_syntax(self):
        """Error message includes the fix: inputs without type, code with type."""
        shared: dict = {}
        with pytest.raises(ValueError) as exc_info:
            run_code_node(
                shared,
                code="text: str\nresult: str = text",
                inputs={"text": "str = hello"},
            )
        error = str(exc_info.value)
        assert "text: hello" in error  # correct inputs syntax
        assert "text: str" in error  # correct code syntax

    def test_non_string_input_not_flagged(self):
        """Non-string input values are never flagged (no pattern to match)."""
        shared: dict = {}
        action = run_code_node(
            shared,
            code="data: list\nresult: int = len(data)",
            inputs={"data": [1, 2, 3]},
        )
        assert action == "default"
        assert shared["result"] == 3

    def test_unknown_type_prefix_not_flagged(self):
        """Values starting with unknown types (not in _TYPE_MAP) pass through."""
        shared: dict = {}
        action = run_code_node(
            shared,
            code="text: str\nresult: str = text",
            inputs={"text": "DataFrame = something"},
        )
        assert action == "default"
        assert shared["result"] == "DataFrame = something"

    def test_value_without_equals_not_flagged(self):
        """Values starting with a type name but no ' = ' pass through."""
        shared: dict = {}
        action = run_code_node(
            shared,
            code="text: str\nresult: str = text",
            inputs={"text": "string value here"},
        )
        assert action == "default"
        assert shared["result"] == "string value here"

    def test_template_reference_with_type_annotation_detected(self):
        """The actual issue #148 scenario: str = ${ref} after template resolution."""
        shared: dict = {}
        with pytest.raises(ValueError, match=r"'text'.*type annotation"):
            run_code_node(
                shared,
                code="text: str\nresult: str = text.upper()",
                # After template resolution, ${fetch.stdout} becomes the actual value
                # but the "str = " prefix is preserved as literal text
                inputs={"text": "str = resolved value from template"},
            )


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
        """Code → Code workflow: template resolution through inputs dict.

        This is the critical integration path. The inputs dict contains
        ${source.result} which must be resolved by the TemplateAwareNodeWrapper
        before the code node's prep() sees it as a native Python object.
        """
        from pflow.runtime import compile_workflow
        from pflow.runtime.engine import WorkflowEngine
        from tests.shared.registry_utils import ensure_test_registry

        registry = ensure_test_registry()

        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "source",
                    "type": "code",
                    "params": {
                        "code": "result: list = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]",
                    },
                },
                {
                    "id": "transform",
                    "type": "code",
                    "params": {
                        "inputs": {
                            "data": "${source.result}",
                            "limit": 5,
                        },
                        "code": "data: list\nlimit: int\n\nresult: list = data[:limit]",
                    },
                },
            ],
            "edges": [{"from": "source", "to": "transform"}],
        }

        workflow = compile_workflow(workflow_ir, registry)
        shared: dict = dict(workflow.resolved_defaults)
        engine = WorkflowEngine()
        engine.run(workflow, shared)

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


class TestAnyAutoInjection:
    def test_any_without_import_works(self):
        shared: dict = {}
        action = run_code_node(
            shared,
            code="x: Any\nresult: int = len(x)",
            inputs={"x": "hello"},
        )
        assert action == "default"
        assert shared["result"] == 5

    def test_any_in_result_annotation_works(self):
        shared: dict = {}
        action = run_code_node(
            shared,
            code="result: Any = {'nested': [1, 2, 3]}",
            inputs={},
        )
        assert action == "default"
        assert shared["result"] == {"nested": [1, 2, 3]}

    def test_typing_any_dotted_form_works(self):
        shared: dict = {}
        action = run_code_node(
            shared,
            code="x: typing.Any\nresult: int = 1",
            inputs={"x": "hello"},
        )
        assert action == "default"
        assert shared["result"] == 1

    @pytest.mark.parametrize("value", [{"k": 1}, [1, 2], "text", 4, True, None])
    def test_any_accepts_all_input_types(self, value):
        shared: dict = {}
        action = run_code_node(
            shared,
            code="x: Any\nresult: int = 1",
            inputs={"x": value},
        )
        assert action == "default"
        assert shared["result"] == 1

    def test_any_union_none_works(self):
        shared: dict = {}
        action = run_code_node(
            shared,
            code="x: Any | None\nresult: int = 1",
            inputs={"x": None},
        )
        assert action == "default"
        assert shared["result"] == 1

    def test_explicit_typing_import_still_works(self):
        shared: dict = {}
        action = run_code_node(
            shared,
            code="from typing import Any\nx: Any\nresult: int = len(x)",
            inputs={"x": "hello"},
        )
        assert action == "default"
        assert shared["result"] == 5

    def test_lowercase_any_rejected(self):
        shared: dict = {}
        with pytest.raises(NonRetriableError, match="Use 'Any'"):
            run_code_node(
                shared,
                code="x: any\nresult: int = 1",
                inputs={"x": "hello"},
            )

    def test_lowercase_any_in_result_rejected(self):
        shared: dict = {}
        with pytest.raises(NonRetriableError, match="## Inputs"):
            run_code_node(
                shared,
                code="result: any = 1",
                inputs={},
            )

    def test_lowercase_any_in_list_generic_rejected(self):
        shared: dict = {}
        with pytest.raises(NonRetriableError, match="Use 'Any'"):
            run_code_node(
                shared,
                code="x: list[any]\nresult: int = 1",
                inputs={"x": [1, 2]},
            )

    def test_lowercase_any_in_forward_reference_rejected(self):
        """String forward-reference annotations (`x: "list[any]"`) must be unwrapped.

        Without this, `ast.unparse` preserves the quotes, the re-parse sees an
        ast.Constant (not ast.Name), the check silently passes, and on Python 3.14+
        PEP 649 leaves the annotation unevaluated at runtime too — the user never
        learns their 'any' is wrong.
        """
        shared: dict = {}
        with pytest.raises(NonRetriableError, match="Use 'Any'"):
            run_code_node(
                shared,
                code='x: "list[any]" = [1, 2]\nresult: int = len(x)',
                inputs={"x": [1, 2]},
            )

    def test_lowercase_any_in_dict_value_rejected(self):
        shared: dict = {}
        with pytest.raises(NonRetriableError, match="Use 'Any'"):
            run_code_node(
                shared,
                code="x: dict[str, any]\nresult: int = 1",
                inputs={"x": {"k": "v"}},
            )

    def test_lowercase_any_in_pipe_union_rejected(self):
        shared: dict = {}
        with pytest.raises(NonRetriableError, match="Use 'Any'"):
            run_code_node(
                shared,
                code="x: int | any\nresult: int = 1",
                inputs={"x": 5},
            )

    def test_lowercase_any_in_optional_rejected(self):
        shared: dict = {}
        with pytest.raises(NonRetriableError, match="Use 'Any'"):
            run_code_node(
                shared,
                code="x: Optional[any]\nresult: int = 1",
                inputs={"x": "hello"},
            )

    def test_literal_string_any_not_rejected(self):
        """`Literal['any']` is a string constant, not a type name — keep it working."""
        shared: dict = {}
        action = run_code_node(
            shared,
            code="from typing import Literal\nx: Literal['any']\nresult: int = 1",
            inputs={"x": "any"},
        )
        assert action == "default"
        assert shared["result"] == 1
