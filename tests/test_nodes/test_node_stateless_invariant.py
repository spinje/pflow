"""Meta-test: nodes must not store execution state on self.

Nodes may be reused across sequential batch items via compile-once caching.
If a node sets self.X in exec() or post(), that state leaks to the next item.
Communication between lifecycle methods must use return values (prep_res, exec_res)
or the shared store — never instance attributes.

Two checks:
1. Direct assignment: self.X = ... (catches most cases)
2. In-place mutation: self.X.append/extend/update/clear/pop/remove/insert(...)
   (catches self.some_list.append(item) which is equally dangerous)

See: src/pflow/nodes/CLAUDE.md "Common Mistakes" #6
"""

import ast
import importlib
import inspect
import pkgutil
from pathlib import Path

import pflow.nodes

# Allowlist for self.X = ... assignments
# (module_path, class_name, method_name, attribute_name, reason)
ALLOWLIST: list[tuple[str, str, str, str, str]] = [
    (
        "pflow.nodes.file.read_file",
        "ReadFileNode",
        "exec",
        "_is_binary",
        "Set on every successful exec path; hasattr guard in post. Anti-pattern but safe.",
    ),
    (
        "pflow.runtime.workflow_executor",
        "WorkflowExecutor",
        "exec",
        "_child_trace_events",
        "Reset to None at start of each exec(). Read by engine for sub-workflow trace embedding.",
    ),
]


def _build_allowlist_set() -> set[tuple[str, str, str, str]]:
    """Build a lookup set from the allowlist (without reason)."""
    return {(mod, cls, method, attr) for mod, cls, method, attr, _ in ALLOWLIST}


def _find_self_assignments(method_node: ast.FunctionDef) -> list[tuple[str, int]]:
    """Find all self.X = ... assignments in a method body.

    Returns list of (attribute_name, line_number).
    """
    assignments: list[tuple[str, int]] = []
    for node in ast.walk(method_node):
        # self.X = value
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                ):
                    assignments.append((target.attr, node.lineno))
        # self.X: type = value (annotated assignment)
        if isinstance(node, ast.AnnAssign) and node.value is not None:
            target = node.target
            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self":
                assignments.append((target.attr, node.lineno))
    return assignments


# Methods that mutate a container in-place. self.X.append(...) is as dangerous as self.X = ...
_MUTATING_METHODS = frozenset({
    "append",
    "extend",
    "insert",
    "remove",
    "pop",
    "clear",  # list
    "update",
    "setdefault",
    "popitem",  # dict
    "add",
    "discard",  # set
})

# Allowlist for self.X.<method>(...) mutations
# (module_path, class_name, method_name, attribute_name, mutating_method, reason)
MUTATION_ALLOWLIST: list[tuple[str, str, str, str, str, str]] = []


def _build_mutation_allowlist_set() -> set[tuple[str, str, str, str, str]]:
    """Build a lookup set from the mutation allowlist (without reason)."""
    return {(mod, cls, method, attr, mut) for mod, cls, method, attr, mut, _ in MUTATION_ALLOWLIST}


def _find_self_mutations(method_node: ast.FunctionDef) -> list[tuple[str, str, int]]:
    """Find all self.X.<mutating_method>(...) calls in a method body.

    Returns list of (attribute_name, mutating_method_name, line_number).
    Catches patterns like self.results.append(item), self.cache.update({...}), etc.
    """
    mutations: list[tuple[str, str, int]] = []
    for node in ast.walk(method_node):
        # Pattern: self.X.method(...)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _MUTATING_METHODS
            and isinstance(node.func.value, ast.Attribute)
            and isinstance(node.func.value.value, ast.Name)
            and node.func.value.value.id == "self"
        ):
            mutations.append((node.func.value.attr, node.func.attr, node.lineno))
    return mutations


def _get_node_classes() -> list[tuple[str, str, type]]:
    """Discover all Node subclasses in src/pflow/nodes/ subdirectories.

    Returns list of (module_path, class_name, class_obj).
    Only includes classes in subdirectories (production nodes), not root-level test fixtures.
    """
    from pflow.core.node import BaseNode

    nodes_dir = Path(pflow.nodes.__file__).parent
    result: list[tuple[str, str, type]] = []

    for subdir in sorted(nodes_dir.iterdir()):
        if not subdir.is_dir() or subdir.name.startswith("_"):
            continue
        package_name = f"pflow.nodes.{subdir.name}"
        try:
            package = importlib.import_module(package_name)
        except ImportError:
            continue

        for _importer, modname, _ispkg in pkgutil.iter_modules(package.__path__):
            full_name = f"{package_name}.{modname}"
            try:
                mod = importlib.import_module(full_name)
            except ImportError:
                continue

            for name, obj in inspect.getmembers(mod, inspect.isclass):
                if issubclass(obj, BaseNode) and obj is not BaseNode and obj.__module__ == full_name:
                    result.append((full_name, name, obj))

    return result


# Also check WorkflowExecutor (not in nodes/ but participates in compile-once)
def _get_workflow_executor() -> tuple[str, str, type]:
    from pflow.runtime.workflow_executor import WorkflowExecutor

    return ("pflow.runtime.workflow_executor", "WorkflowExecutor", WorkflowExecutor)


DANGEROUS_METHODS = {"exec", "post", "exec_fallback"}


def _check_method_violations(
    module_path: str,
    class_name: str,
    method: ast.FunctionDef,
    allowed: set[tuple[str, str, str, str]],
    mutation_allowed: set[tuple[str, str, str, str, str]],
) -> list[str]:
    """Check a single method for self.X assignments and mutations."""
    violations: list[str] = []
    for attr_name, lineno in _find_self_assignments(method):
        if (module_path, class_name, method.name, attr_name) not in allowed:
            violations.append(
                f"  {module_path}.{class_name}.{method.name}(): "
                f"self.{attr_name} = ... (line {lineno})\n"
                f"    Nodes must not store execution state on self — "
                f"use return values or shared store instead.\n"
                f"    If this is intentionally safe, add to ALLOWLIST in this test."
            )
    for attr_name, mut_method, lineno in _find_self_mutations(method):
        if (module_path, class_name, method.name, attr_name, mut_method) not in mutation_allowed:
            violations.append(
                f"  {module_path}.{class_name}.{method.name}(): "
                f"self.{attr_name}.{mut_method}(...) (line {lineno})\n"
                f"    In-place mutation of instance state breaks compile-once — "
                f"state leaks between sequential batch items.\n"
                f"    If this is intentionally safe, add to MUTATION_ALLOWLIST in this test."
            )
    return violations


def _scan_class_for_violations(
    module_path: str,
    class_name: str,
    cls: type,
    allowed: set[tuple[str, str, str, str]],
    mutation_allowed: set[tuple[str, str, str, str, str]],
) -> list[str]:
    """Scan a single class for self.X assignments and mutations in dangerous methods."""
    try:
        source = inspect.getsource(cls)
        tree = ast.parse(source)
    except (OSError, TypeError):
        return []

    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name in DANGEROUS_METHODS:
                violations.extend(_check_method_violations(module_path, class_name, item, allowed, mutation_allowed))
    return violations


def _check_allowlist_entry_exists(module_path: str, class_name: str, method_name: str, attr_name: str) -> bool:
    """Check whether an allowlisted self.X assignment still exists in the code."""
    try:
        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        source = inspect.getsource(cls)
        tree = ast.parse(source)
    except (ImportError, AttributeError, OSError):
        return False

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        for item in node.body:
            if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if item.name != method_name:
                continue
            for a_name, _ in _find_self_assignments(item):
                if a_name == attr_name:
                    return True
    return False


def test_no_self_assignments_in_exec_or_post():
    """No production node stores execution state on self in exec/post/exec_fallback.

    This enforces the compile-once invariant: the same node instance may be reused
    across sequential batch items. State set in exec() would leak to the next item.

    Checks both direct assignment (self.X = ...) and in-place mutation
    (self.X.append/extend/update/...) — both break compile-once equally.
    """
    allowed = _build_allowlist_set()
    mutation_allowed = _build_mutation_allowlist_set()
    violations: list[str] = []

    classes = _get_node_classes()
    classes.append(_get_workflow_executor())

    for module_path, class_name, cls in classes:
        violations.extend(_scan_class_for_violations(module_path, class_name, cls, allowed, mutation_allowed))

    if violations:
        msg = (
            f"Found {len(violations)} instance state violation(s) in exec/post/exec_fallback "
            f"(compile-once invariant):\n\n"
            + "\n\n".join(violations)
            + "\n\nSee src/pflow/nodes/CLAUDE.md 'Common Mistakes' #6."
        )
        raise AssertionError(msg)


def test_allowlist_entries_still_exist():
    """Every allowlisted exception must still exist in the code.

    Prevents stale allowlist entries from accumulating after refactors.
    """
    stale: list[str] = []

    for module_path, class_name, method_name, attr_name, reason in ALLOWLIST:
        if not _check_allowlist_entry_exists(module_path, class_name, method_name, attr_name):
            stale.append(f"  {module_path}.{class_name}.{method_name}(): self.{attr_name}\n    Reason was: {reason}")

    if stale:
        msg = (
            f"Found {len(stale)} stale allowlist entry/entries — "
            f"the code no longer has these assignments:\n\n"
            + "\n\n".join(stale)
            + "\n\nRemove from ALLOWLIST in this test."
        )
        raise AssertionError(msg)
