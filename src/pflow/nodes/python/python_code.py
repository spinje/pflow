"""Execute Python code with typed native object inputs.

This node executes Python code in-process using exec(), providing direct access
to input data as native Python objects. All input variables and the result
variable must have type annotations in the code string.

Example workflow usage (.pflow.md):

    ### transform

    Filter data to first N items.

    - type: code
    - inputs:
        data: ${fetch.result}
        count: 10

    ```python code
    data: list
    count: int

    result: list = data[:count]
    ```
"""

import ast
import io
import logging
import re
import sys
import traceback
import typing as _typing_module
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from typing import Any, Optional

from pflow.core.node import Node
from pflow.nodes.file.exceptions import NonRetriableError

logger = logging.getLogger(__name__)

# Mapping from type annotation strings to Python types for isinstance() checks.
# Only the outer (base) type is validated — generic parameters are ignored.
# e.g. "list[dict]" validates isinstance(value, list), not element types.
_TYPE_MAP: dict[str, type | tuple[type, ...]] = {
    "int": int,
    "float": (int, float),  # int is valid where float is expected
    "str": str,
    "bool": bool,
    "list": list,
    "dict": dict,
    "set": set,
    "tuple": tuple,
    "bytes": bytes,
}


def _extract_annotations(code: str) -> dict[str, str]:
    """Extract type annotations from Python code using AST parsing.

    Finds all annotated assignments (``name: type`` or ``name: type = value``)
    at the module level and returns a mapping of variable names to their
    annotation strings.

    Args:
        code: Python source code to parse.

    Returns:
        Dict mapping variable names to type annotation strings.
        Example: ``{"data": "list[dict]", "result": "dict"}``

    Raises:
        SyntaxError: If the code contains invalid Python syntax.
    """
    tree = ast.parse(code)
    annotations: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            annotations[node.target.id] = ast.unparse(node.annotation)
    return annotations


def _is_optional_type(type_str: str) -> bool:
    """Check if a type annotation allows None.

    Recognizes ``Optional[T]``, ``T | None``, and ``None | T`` forms.
    """
    stripped = type_str.strip()
    # Optional[T] or typing.Optional[T]
    if (stripped.startswith("Optional[") or stripped.startswith("typing.Optional[")) and stripped.endswith("]"):
        return True
    # T | None or None | T (handles spaces around |)
    parts = [p.strip() for p in stripped.split("|")]
    return "None" in parts


def _get_inner_optional_type(type_str: str) -> Optional[str]:
    """Extract the inner type from an Optional annotation.

    Returns the inner type string if the annotation is optional, else None.

    Examples::

        'Optional[str]'     -> 'str'
        'str | None'        -> 'str'
        'None | str'        -> 'str'
        'list[str] | None'  -> 'list[str]'
        'str'               -> None
    """
    stripped = type_str.strip()
    # typing.Optional[T] -> T
    if stripped.startswith("typing.Optional[") and stripped.endswith("]"):
        return stripped[len("typing.Optional[") : -1].strip()
    # Optional[T] -> T
    if stripped.startswith("Optional[") and stripped.endswith("]"):
        return stripped[len("Optional[") : -1].strip()
    # T | None or None | T
    parts = [p.strip() for p in stripped.split("|")]
    if "None" in parts:
        non_none = [p for p in parts if p != "None"]
        if non_none:
            return " | ".join(non_none)
    return None


def _get_outer_type(type_str: str) -> type | tuple[type, ...] | None:
    """Resolve a type annotation string to a Python type for isinstance() checks.

    Strips generic parameters so ``list[dict[str, Any]]`` resolves to ``list``.
    Decomposes optional types: ``str | None`` resolves to ``(str, type(None))``.
    Returns None for types not in ``_TYPE_MAP`` (e.g. user-defined classes),
    which skips the isinstance check.
    """
    # Handle optional types: extract inner type and add NoneType
    inner = _get_inner_optional_type(type_str)
    if inner is not None:
        inner_type = _get_outer_type(inner)
        if inner_type is None:
            return None  # Unknown inner type — skip check
        if isinstance(inner_type, tuple):
            return (*inner_type, type(None))
        return (inner_type, type(None))

    base = type_str.split("[")[0].strip()
    return _TYPE_MAP.get(base)


# Typing-module names that have a modern lowercase built-in generic (PEP 585).
# pflow prefers these over the typing-module spellings.
_MODERN_GENERIC_NAMES = frozenset({"List", "Dict", "Tuple", "Set", "FrozenSet", "Type"})

# Typing-module names that genuinely require explicit import (no modern built-in replacement).
_REQUIRES_TYPING_IMPORT = frozenset({
    "Literal",
    "TypeVar",
    "Callable",
    "Final",
    "ClassVar",
    "Iterable",
    "Iterator",
    "Sequence",
    "Mapping",
})

# Union of the three typing-name families pflow proactively rejects inside
# annotations. Rejecting at AST-walk time (prep) keeps the opinionated guidance
# reachable across Python versions: PEP 649 (3.14+) defers annotation evaluation,
# so the NameError fallback in `_format_exec_error` never fires for code like
# `x: Union[int, str] = 1`. Typing names used as *values* (`x = Union[int, str]`)
# still hit the NameError path — eager evaluation there is unchanged.
_REJECTED_ANNOTATION_NAMES = _MODERN_GENERIC_NAMES | {"Union"} | _REQUIRES_TYPING_IMPORT


def _suggest_for_nameerror(var_name: str) -> str:
    """Return an opinionated, canonical fix suggestion for a NameError.

    pflow auto-injects `Any`, `Optional`, and the `typing` module — other
    typing names produce a NameError. Rather than listing multiple options,
    this emits ONE canonical fix per case, preferring modern Python (PEP 585
    lowercase generics, PEP 604 pipe unions) over typing-module spellings.
    """
    if var_name in _MODERN_GENERIC_NAMES:
        lower = var_name.lower()
        return (
            f"  - Use '{lower}[...]' instead — Python 3.9+ supports lowercase built-in generics (PEP 585).\n"
            f"    Example: 'x: {lower}[str]' instead of 'x: {var_name}[str]'."
        )
    if var_name == "Union":
        return (
            "  - Use pipe syntax instead: 'A | B' (PEP 604, Python 3.10+).\n"
            "    Example: 'x: int | str' instead of 'x: Union[int, str]'."
        )
    if var_name in _REQUIRES_TYPING_IMPORT:
        return (
            f"  - Add 'from typing import {var_name}' at the top of your code block.\n"
            "    (pflow auto-injects 'Any' and 'Optional' — other typing names need explicit import.)"
        )
    # Not a known typing name — fall back to the input-variable suggestions.
    return (
        f'  - Add \'{var_name}\' to the inputs dict: "inputs": {{"{var_name}": ...}}\n'
        f"  - Or define '{var_name}' in the code before use\n"
        "  - Check for typos in variable names"
    )


def _extract_imported_names(code: str) -> frozenset[str]:
    """Return names bound by top-level ``import`` / ``from ... import`` statements.

    Used by ``_check_annotation_vocabulary`` to avoid rejecting typing names that
    the user imported explicitly (e.g., ``from typing import Literal``).
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return frozenset()
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imported.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.asname or alias.name.split(".")[0])
    return frozenset(imported)


def _check_annotation_vocabulary(code: str, annotations: dict[str, str]) -> None:
    """Reject lowercase ``any`` and forgotten typing-module imports in annotations.

    Walks each annotation as an AST so nested occurrences
    (``list[any]``, ``dict[str, any]``, ``int | any``) are caught — not just the
    outermost token. String literals like ``Literal['any']`` stay as
    ``ast.Constant`` and are correctly ignored.

    Rejects ``Union`` / ``List`` / ``Literal`` etc. eagerly (at prep) when they
    aren't imported, because PEP 649 (Python 3.14+) defers annotation evaluation
    — the NameError fallback in ``_format_exec_error`` only catches these names
    when used as *values*, not annotations. Users who explicitly
    ``from typing import X`` are left alone; the nudge targets forgotten imports.
    """
    imported = _extract_imported_names(code)
    for var_name, annotation in annotations.items():
        try:
            tree = ast.parse(annotation, mode="eval")
        except SyntaxError:
            # Malformed annotations surface via the existing NameError path at exec time.
            continue
        # Unwrap string forward-reference annotations (`x: "list[any]"`) so the
        # inner type is walked, not treated as an opaque ast.Constant. Without this
        # the outer string hides nested violations — which PEP 649 (3.14+) leaves
        # uncaught at runtime too, since the annotation is never evaluated.
        if isinstance(tree.body, ast.Constant) and isinstance(tree.body.value, str):
            try:
                tree = ast.parse(tree.body.value, mode="eval")
            except SyntaxError:
                continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Name):
                continue
            if node.id == "any":
                raise NonRetriableError(
                    f"Invalid type annotation for '{var_name}': 'any' (lowercase).\n\n"
                    "Use 'Any' (capitalized) in Python code blocks. "
                    "pflow auto-injects `typing.Any` — no import needed.\n"
                    f"  {var_name}: Any\n\n"
                    "Note: lowercase 'any' is the legal spelling in `## Inputs` / `## Outputs` "
                    "sections (e.g., `- type: any`), but Python annotations must use 'Any' (capitalized)."
                )
            if node.id in _REJECTED_ANNOTATION_NAMES and node.id not in imported:
                raise NonRetriableError(
                    f"Invalid type annotation for '{var_name}': '{node.id}' is not defined.\n\n"
                    f"{_suggest_for_nameerror(node.id)}"
                )


def extract_optional_input_keys(code: str, input_keys: set[str]) -> set[str]:
    """Return input keys whose code annotations include None.

    Used by the compiler to identify which code node inputs should tolerate
    unresolved templates (i.e., when the source node didn't execute in a
    conditional branch).

    Args:
        code: Python code string with type annotations.
        input_keys: Set of input parameter names.

    Returns:
        Set of input key names annotated as optional (``T | None`` or ``Optional[T]``).
    """
    try:
        annotations = _extract_annotations(code)
    except SyntaxError:
        return set()

    optional_keys: set[str] = set()
    for key in input_keys:
        type_str = annotations.get(key)
        if type_str and _is_optional_type(type_str):
            optional_keys.add(key)
    return optional_keys


def _extract_error_location(exc: Exception, code: str, code_source_line: int = 0) -> str:
    """Extract a human-readable error location from an exception's traceback.

    Filters traceback to frames from user code (filename='<code>') and
    returns the line number with the source text for context.

    When *code_source_line* is set (the 1-based line in the .pflow.md file
    where the code block content starts), the workflow-file line is included
    so the user can jump straight to the right place.

    Returns empty string if no location info is available (e.g. TimeoutError
    has no traceback from user code).
    """
    tb = getattr(exc, "__traceback__", None)
    if tb is None:
        return ""

    # Filter to frames from user code only
    frames = traceback.extract_tb(tb)
    user_frames = [f for f in frames if f.filename == "<code>"]
    if not user_frames:
        return ""

    last = user_frames[-1]
    lineno = last.lineno
    if lineno is None:
        return ""

    lines = code.splitlines()
    source_line = lines[lineno - 1].strip() if lineno <= len(lines) else ""

    # Build labeled Location + Source lines
    if code_source_line:
        workflow_line = code_source_line + lineno - 1
        location = f"  Location: line {workflow_line} (line {lineno} in code block)"
    else:
        location = f"  Location: line {lineno} in code block"

    if source_line:
        return f"{location}\n  Source: {source_line}"
    return location


class PythonCodeNode(Node):
    """Execute Python code with typed inputs and result capture.

    Runs Python code in-process with native object access. All input variables
    must have type annotations in code. Result must be assigned to an annotated
    ``result`` variable.

    Interface:
    - Params: code: str  # Python code to execute (required, must contain type annotations)
    - Params: inputs: dict  # Variable name to value mapping (optional, default: {})
    - Params: timeout: int  # Execution timeout in seconds (optional, default: 30)
    - Params: requires: list  # Package dependencies for documentation (optional)
    - Writes: shared["result"]: any  # Value of result variable after execution
    - Writes: shared["stdout"]: str  # Captured print() output
    - Writes: shared["stderr"]: str  # Captured stderr output
    - Writes: shared["error"]: str  # Error message if execution failed
    - Actions: default (success), error (failure), <custom> (dynamic routing via next variable)

    Dynamic routing:
        Code can set ``next: str = "target-node-id"`` to control which node
        runs after this one. When ``next`` is set, it becomes the action returned
        by post(). The ``result`` annotation is optional when ``next`` is declared.
    """

    # Override auto-derived name so workflow type is "code" (not "python-code").
    name = "code"

    def __init__(self) -> None:
        """Initialize with minimal retries — code execution is deterministic."""
        super().__init__(max_retries=1, wait=0)

    # ------------------------------------------------------------------
    # prep: validate params, parse AST, check types
    # ------------------------------------------------------------------

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        """Validate parameters, extract annotations, and check input types.

        Returns a prep dict consumed by exec().

        Raises:
            ValueError: Missing/invalid code or timeout, missing annotations.
            SyntaxError: If the code string is not valid Python.
            TypeError: If an input value does not match its declared type.
        """
        code = self._validate_code()
        timeout = self._validate_timeout()
        inputs = self._validate_inputs()
        requires = self.params.get("requires", [])

        # Parse code — SyntaxError propagates with line info
        annotations = _extract_annotations(code)

        # Validate annotations exist for every input variable
        self._check_input_annotations(inputs, annotations)

        # Detect type annotations accidentally written in YAML inputs (#148)
        self._check_input_annotation_syntax(inputs, annotations)
        _check_annotation_vocabulary(code, annotations)

        # Validate result or next annotation exists
        has_result = "result" in annotations
        has_next = "next" in annotations

        if not has_result and not has_next:
            raise ValueError(
                "Code must declare result type annotation (result: <type> = ...) "
                "or next type annotation (next: str = ...) for routing"
            )

        # Validate next annotation type if present
        if has_next:
            next_type_str = annotations["next"]
            next_outer_type = _get_outer_type(next_type_str)
            if next_outer_type is not None and next_outer_type is not str:
                raise ValueError(
                    f"'next' must be annotated as str, got {next_type_str}\n\nExample: next: str = \"target-node-id\""
                )

        # Validate input types against annotations
        self._check_input_types(inputs, annotations)

        return {
            "code": code,
            "inputs": inputs,
            "timeout": timeout,
            "requires": requires,
            "annotations": annotations,
            "code_source_line": self.params.get("_code_source_line", 0),
            "has_result": has_result,
        }

    # ------------------------------------------------------------------
    # exec: run code with timeout + stdout/stderr capture
    # ------------------------------------------------------------------

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        """Execute Python code in a thread with timeout.

        NO try/except — let exceptions bubble up for PocketFlow retry mechanism.
        """
        code = prep_res["code"]
        inputs = prep_res["inputs"]
        timeout = prep_res["timeout"]

        # Build namespace with unrestricted builtins + typing + input variables
        namespace: dict[str, Any] = {"__builtins__": __builtins__}
        namespace["typing"] = _typing_module
        namespace["Optional"] = _typing_module.Optional
        namespace["Any"] = _typing_module.Any
        namespace.update(inputs)

        # Execute in thread with stdout/stderr capture.
        # IMPORTANT: Do NOT use `with ThreadPoolExecutor` — its __exit__ calls
        # shutdown(wait=True) which blocks until the thread finishes, defeating
        # the timeout for truly stuck code (infinite loops, blocking I/O).
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(self._execute_code, code, namespace)
        try:
            future.result(timeout=timeout)
        finally:
            # wait=False: don't block if the thread is still running.
            # The zombie thread is safe because _execute_code uses a guarded
            # restore for sys.stdout/sys.stderr (see its docstring and #138).
            pool.shutdown(wait=False, cancel_futures=True)

        # Extract captured output
        stdout = namespace.pop("__stdout__", "")
        stderr = namespace.pop("__stderr__", "")

        # Extract result if declared
        has_result = prep_res["has_result"]

        if has_result:
            if "result" not in namespace:
                raise ValueError("Code must set 'result' variable. Add: result = <your_value>")
            result_value = namespace["result"]
        else:
            result_value = None

        exec_result: dict[str, Any] = {
            "result": result_value,
            "stdout": stdout,
            "stderr": stderr,
        }

        # Capture next variable if user code set it (for routing)
        if "next" in namespace:
            exec_result["next"] = namespace["next"]

        return exec_result

    # ------------------------------------------------------------------
    # exec_fallback: format errors after retry exhaustion
    # ------------------------------------------------------------------

    def exec_fallback(self, prep_res: dict[str, Any], exc: Exception) -> dict[str, Any]:
        """Produce a user-friendly error dict after execution failure."""
        error = self._format_exec_error(exc, prep_res)
        return {
            "result": None,
            "stdout": "",
            "stderr": "",
            "error": error,
        }

    # ------------------------------------------------------------------
    # post: write results to shared store, return action
    # ------------------------------------------------------------------

    def post(
        self,
        shared: dict[str, Any],
        prep_res: dict[str, Any],
        exec_res: dict[str, Any],
    ) -> str:
        """Store results in shared store and determine next action."""
        # Check for error from exec_fallback
        if "error" in exec_res:
            shared["error"] = exec_res["error"]
            shared["stdout"] = exec_res.get("stdout", "")
            shared["stderr"] = exec_res.get("stderr", "")
            return "error"

        annotations = prep_res["annotations"]
        has_result = prep_res["has_result"]

        # Validate and store result if declared
        if has_result:
            result_value = exec_res["result"]
            result_type_str = annotations["result"]
            expected_type = _get_outer_type(result_type_str)

            if expected_type is not None and not isinstance(result_value, expected_type):
                actual_type = type(result_value).__name__
                shared["error"] = (
                    f"Result declared as {result_type_str} but code returned {actual_type}\n\n"
                    f"Suggestions:\n"
                    f"  - Change result type annotation to: result: {actual_type}\n"
                    f"  - Or convert the value to match the declared type"
                )
                shared["stdout"] = exec_res.get("stdout", "")
                shared["stderr"] = exec_res.get("stderr", "")
                return "error"

            shared["result"] = result_value

        # Always store stdout/stderr
        shared["stdout"] = exec_res.get("stdout", "")
        shared["stderr"] = exec_res.get("stderr", "")

        # Determine action: use next if set, otherwise default
        if "next" in exec_res:
            next_value = exec_res["next"]
            if not isinstance(next_value, str):
                actual_type = type(next_value).__name__
                shared["error"] = (
                    f"'next' must be a string, got {actual_type}: {next_value!r}\n\n"
                    f"Suggestions:\n"
                    f"  - Convert to string: next: str = str(your_value)\n"
                    f'  - Or use a string literal: next: str = "target-node"'
                )
                return "error"
            if not next_value:
                shared["error"] = (
                    "'next' must not be empty\n\n"
                    "Suggestions:\n"
                    '  - Set to a valid node ID: next: str = "target-node"\n'
                    "  - Or remove next to follow default routing"
                )
                return "error"
            return next_value

        return "default"

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _execute_code(code: str, namespace: dict[str, Any]) -> None:
        """Execute code string with stdout/stderr capture.

        Runs in a worker thread via ThreadPoolExecutor. Captured output is
        stored in the namespace under ``__stdout__`` and ``__stderr__`` keys.

        Uses compile() with filename='<code>' so traceback frames from user
        code are identifiable and line numbers can be extracted for error messages.

        IMPORTANT: This method runs in a worker thread. We must NOT use
        redirect_stdout/redirect_stderr here — they modify global sys.stdout/
        sys.stderr which is not thread-safe. If this thread outlives its caller
        (e.g. on timeout with pool.shutdown(wait=False)), the __exit__ would
        restore stale values, corrupting streams for whatever code is running
        on the main thread at that point.

        Instead, we save/restore manually and guard the restore with an
        identity check: only restore if sys.stdout/sys.stderr still point to
        our buffers. A zombie thread that wakes up after the main thread has
        moved on will see different objects and skip the restore.
        """
        compiled = compile(code, "<code>", "exec")
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = stdout_buf
        sys.stderr = stderr_buf
        try:
            exec(compiled, namespace)  # noqa: S102
        finally:
            # Only restore if sys.stdout/sys.stderr still point to our buffers.
            # If another thread (or the main thread after a timeout) has replaced
            # them, restoring our stale saved values would corrupt that thread's
            # streams. In that case, just leave them as-is.
            if sys.stdout is stdout_buf:
                sys.stdout = old_stdout
            if sys.stderr is stderr_buf:
                sys.stderr = old_stderr
        namespace["__stdout__"] = stdout_buf.getvalue()
        namespace["__stderr__"] = stderr_buf.getvalue()

    def _validate_code(self) -> str:
        """Extract and validate the code parameter."""
        code = self.params.get("code")
        if not isinstance(code, str) or not code.strip():
            raise ValueError(
                "Missing required 'code' parameter\n\n"
                "Provide a Python code string with type-annotated inputs and result.\n"
                "Example:\n"
                '  "code": "data: list\\nresult: list = data[:10]"'
            )
        return code

    def _validate_timeout(self) -> int | float:
        """Extract and validate the timeout parameter."""
        timeout = self.params.get("timeout", 30)
        try:
            timeout = float(timeout)
        except (TypeError, ValueError):
            raise ValueError(f"Timeout must be a positive number, got {timeout!r}") from None
        if timeout <= 0:
            raise ValueError(f"Timeout must be a positive number, got {timeout}")
        return timeout

    def _validate_inputs(self) -> dict[str, Any]:
        """Extract and validate the inputs parameter."""
        inputs = self.params.get("inputs", {})
        if not isinstance(inputs, dict):
            raise TypeError(f"'inputs' parameter must be a dict, got {type(inputs).__name__}")
        return inputs

    @staticmethod
    def _check_input_annotations(inputs: dict[str, Any], annotations: dict[str, str]) -> None:
        """Verify every input variable has a type annotation in the code."""
        missing = [name for name in inputs if name not in annotations]
        if missing:
            hints = [f"  {name}: <type>" for name in missing]
            raise ValueError(
                f"Input(s) missing type annotation in code: {', '.join(missing)}\nAdd annotations:\n" + "\n".join(hints)
            )

    # Pattern matching type annotations accidentally written in YAML input values.
    # Matches: "str = ...", "list[dict] = ...", "Optional[str] = ...", etc.
    _INPUT_TYPE_ANNOTATION_PATTERN = re.compile(r"^([a-zA-Z]\w*(?:\[[\w\[\], |]+\])?)\s*=\s*\S")

    @staticmethod
    def _check_input_annotation_syntax(inputs: dict[str, Any], annotations: dict[str, str]) -> None:
        """Detect type annotations accidentally written in YAML input values.

        When users see ``text: str`` in the code block, they naturally mirror
        the syntax in YAML inputs: ``text: str = ${ref}``. YAML treats the
        whole right side as a string, silently corrupting the value to
        ``"str = <resolved>"`` instead of just ``"<resolved>"``.

        Cross-references against code annotations to minimize false positives:
        only flags values where the prefix matches a known type name AND the
        code declares a matching annotation for that variable.
        """
        for var_name, value in inputs.items():
            if not isinstance(value, str):
                continue
            match = PythonCodeNode._INPUT_TYPE_ANNOTATION_PATTERN.match(value)
            if not match:
                continue
            type_prefix = match.group(1)
            # Cross-reference: only flag if the type prefix base matches a known type
            base_type = type_prefix.split("[")[0]
            if base_type not in _TYPE_MAP:
                continue
            # And the variable has a code annotation
            if var_name not in annotations:
                continue
            # Extract the actual value after "type = "
            actual_value = value[match.end() - 1 :]  # -1 to include the \S char
            raise ValueError(
                f"Input '{var_name}' appears to have a type annotation: \"{value}\"\n\n"
                f"Type annotations belong in the code block, not in inputs.\n"
                f"Write:\n"
                f"  - inputs:\n"
                f"      {var_name}: {actual_value}\n\n"
                f"  ```python code\n"
                f"  {var_name}: {annotations[var_name]}\n"
                f"  ```"
            )

    @staticmethod
    def _check_input_types(inputs: dict[str, Any], annotations: dict[str, str]) -> None:
        """Validate each input value matches its declared outer type."""
        for var_name, value in inputs.items():
            type_str = annotations.get(var_name)
            if type_str is None:
                continue  # already checked in _check_input_annotations
            expected = _get_outer_type(type_str)
            if expected is None:
                continue  # unknown type — skip check
            if not isinstance(value, expected):
                actual = type(value).__name__
                raise TypeError(
                    f"Input '{var_name}' expects {type_str} but received {actual}\n\n"
                    f"Suggestions:\n"
                    f"  - Change the type annotation to: {var_name}: {actual}\n"
                    f"  - Or convert the input value to {type_str}\n"
                    f"  - Or use `Any` to accept any type: {var_name}: Any"
                )

    @staticmethod
    def _format_exec_error(exc: Exception, prep_res: dict[str, Any]) -> str:
        """Format an execution exception into a user-friendly error string.

        Extracts line number from traceback when available, and provides
        actionable suggestions for each error type so AI agents can self-correct.
        """
        code = prep_res.get("code", "")
        code_source_line = prep_res.get("code_source_line", 0)
        location = _extract_error_location(exc, code, code_source_line)

        if isinstance(exc, (TimeoutError, FuturesTimeoutError)):
            timeout = prep_res["timeout"]
            return (
                f"Python code execution timed out after {timeout} seconds\n\n"
                f"Suggestions:\n"
                f'  - Increase timeout: "timeout": {int(timeout * 2)}\n'
                f"  - Check for infinite loops or blocking I/O in code\n"
                f"  - Break long computation into multiple code nodes"
            )
        if isinstance(exc, NameError):
            var_name = getattr(exc, "name", str(exc))
            msg = f"Undefined variable '{var_name}'"
            if location:
                msg += f"\n{location}"
            suggestion = _suggest_for_nameerror(var_name)
            msg += f"\n\nSuggestions:\n{suggestion}"
            return msg
        if isinstance(exc, ImportError):
            module = getattr(exc, "name", str(exc))
            msg = f"Module '{module}' not found"
            if location:
                msg += f"\n{location}"
            msg += (
                f"\n\nSuggestions:\n"
                f"  - Install with: pipx inject pflow-cli {module}\n"
                f"  - Or with uv (list existing extras first — uv replaces, not adds):\n"
                f"    uv tool list --show-with\n"
                f"    uv tool install --with {module} --with <existing-extras> pflow-cli\n"
                f'  - Document dependency: "requires": ["{module}"]'
            )
            return msg

        # Generic runtime error — include line number + traceback context
        exc_type = type(exc).__name__
        msg = f"{exc_type}: {exc}"
        if location:
            msg += f"\n{location}"
        msg += (
            "\n\nSuggestions:\n"
            "  - Fix the error in the code string above\n"
            "  - Check input data types and values match expectations"
        )
        return msg
