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
import traceback
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from contextlib import redirect_stderr, redirect_stdout
from typing import Any

from pflow.pocketflow import Node

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


def _get_outer_type(type_str: str) -> type | tuple[type, ...] | None:
    """Resolve a type annotation string to a Python type for isinstance() checks.

    Strips generic parameters so ``list[dict[str, Any]]`` resolves to ``list``.
    Returns None for types not in ``_TYPE_MAP`` (e.g. user-defined classes),
    which skips the isinstance check.
    """
    base = type_str.split("[")[0].strip()
    return _TYPE_MAP.get(base)


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
    - Actions: default (success), error (failure)
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

        # Validate result annotation exists
        if "result" not in annotations:
            raise ValueError("Code must declare result type annotation: result: <type> = ...")

        # Validate input types against annotations
        self._check_input_types(inputs, annotations)

        return {
            "code": code,
            "inputs": inputs,
            "timeout": timeout,
            "requires": requires,
            "annotations": annotations,
            "code_source_line": self.params.get("_code_source_line", 0),
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

        # Build namespace with unrestricted builtins + input variables
        namespace: dict[str, Any] = {"__builtins__": __builtins__}
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
            # wait=False: don't block if the thread is still running (zombie
            # thread is an acceptable tradeoff — documented in spec).
            pool.shutdown(wait=False, cancel_futures=True)

        # Extract captured output
        stdout = namespace.pop("__stdout__", "")
        stderr = namespace.pop("__stderr__", "")

        # Verify result variable was set
        if "result" not in namespace:
            raise ValueError("Code must set 'result' variable. Add: result = <your_value>")

        return {
            "result": namespace["result"],
            "stdout": stdout,
            "stderr": stderr,
        }

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

        # Validate result type against annotation
        annotations = prep_res["annotations"]
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

        # Success — write outputs
        shared["result"] = result_value
        shared["stdout"] = exec_res.get("stdout", "")
        shared["stderr"] = exec_res.get("stderr", "")
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
        """
        compiled = compile(code, "<code>", "exec")
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
            exec(compiled, namespace)  # noqa: S102
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
                    f"  - Or convert the input value to {type_str}"
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
            msg += (
                f"\n\nSuggestions:\n"
                f'  - Add \'{var_name}\' to the inputs dict: "inputs": {{"{var_name}": ...}}\n'
                f"  - Or define '{var_name}' in the code before use\n"
                f"  - Check for typos in variable names"
            )
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
