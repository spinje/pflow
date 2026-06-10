"""Phase-0 corpus sweep for a TRANSFORM pseudo-kind (Task 168 follow-on discussion).

Question: how many code nodes in the example corpus are pure data transforms
(reshape inputs -> result, no external effects), detectable fail-closed from the
AST? Also: how many are hybrids (transform + sets `next`), and for Level-2
feasibility, how many build `result` as a literal dict whose keys we could
extract as output ports?

Mirrors the condition-labels Phase-0 playbook (scratchpads/condition-labels/).
Run: uv run python scratchpads/transform-role/sweep.py
"""

from __future__ import annotations

import ast
import hashlib
from collections import Counter
from pathlib import Path

from pflow.execution.graph_service import resolve_validate_build

EXAMPLES = Path("examples")
EXCLUDED_DIRS = {"invalid", "legacy", "real-workflows"}

# ---------------------------------------------------------------- classifier

ALLOWED_MODULES = {
    "json", "re", "math", "datetime", "collections", "itertools",
    "textwrap", "string", "copy", "functools", "base64", "hashlib",
    "statistics", "difflib",
}

ALLOWED_BUILTIN_CALLS = {
    "len", "str", "int", "float", "bool", "list", "dict", "set", "tuple",
    "sorted", "reversed", "enumerate", "zip", "range", "min", "max", "sum",
    "abs", "round", "any", "all", "repr", "format", "isinstance", "filter",
    "map", "divmod", "hash", "frozenset", "ord", "chr", "print",
    # exception constructors — `raise ValueError(...)` is a pure failure path
    # (the engine catches it), not an external effect
    "Exception", "ValueError", "TypeError", "RuntimeError", "KeyError",
    "IndexError", "ZeroDivisionError", "StopIteration", "AssertionError",
}

FORBIDDEN_CALLS = {
    "open", "exec", "eval", "compile", "__import__", "input",
    "globals", "locals", "vars", "getattr", "setattr", "delattr",
}


class _Purity(ast.NodeVisitor):
    """Fail-closed purity walk: collect every reason this code is NOT a pure
    transform. Empty reasons == classified TRANSFORM."""

    def __init__(self) -> None:
        self.reasons: list[str] = []
        self.assigns_result = False
        self.sets_next = False
        self.imported: set[str] = set()
        self.result_dict_keys: list[list[str]] = []  # per literal-dict result assign
        self.result_nonliteral = 0  # result assigned something not a literal dict

    # -- imports ------------------------------------------------------------
    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root = alias.name.split(".")[0]
            self.imported.add(alias.asname or root)
            if root not in ALLOWED_MODULES:
                self.reasons.append(f"import:{root}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        root = (node.module or "").split(".")[0]
        if root not in ALLOWED_MODULES:
            self.reasons.append(f"from-import:{root}")
        for alias in node.names:
            self.imported.add(alias.asname or alias.name)
        self.generic_visit(node)

    # -- calls ---------------------------------------------------------------
    def visit_Call(self, node: ast.Call) -> None:
        fn = node.func
        if isinstance(fn, ast.Name):
            if fn.id in FORBIDDEN_CALLS:
                self.reasons.append(f"call:{fn.id}")
            elif fn.id not in ALLOWED_BUILTIN_CALLS and fn.id not in self.imported and not self._is_local(fn.id):
                self.reasons.append(f"call:{fn.id}")
        elif isinstance(fn, ast.Attribute):
            base = fn.value
            # module.attr(...) — gate on the module whitelist; method calls on
            # values (x.strip(), d.get()) are allowed (pure-ish reshaping).
            if isinstance(base, ast.Name) and base.id in self.imported_module_names:
                pass  # already gated at import
        self.generic_visit(node)

    def _is_local(self, name: str) -> bool:
        return name in self.local_defs

    # -- effects-shaped statements -------------------------------------------
    def visit_With(self, node: ast.With) -> None:
        self.reasons.append("with-block")
        self.generic_visit(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self.reasons.append("with-block")
        self.generic_visit(node)

    def visit_Global(self, node: ast.Global) -> None:
        self.reasons.append("global")

    # -- result / next tracking ------------------------------------------------
    def _record_target(self, target: ast.expr, value: ast.expr | None) -> None:
        if isinstance(target, ast.Name):
            if target.id == "result":
                self.assigns_result = True
                if isinstance(value, ast.Dict) and all(
                    isinstance(k, ast.Constant) and isinstance(k.value, str) for k in value.keys
                ):
                    self.result_dict_keys.append([k.value for k in value.keys])  # type: ignore[union-attr]
                else:
                    self.result_nonliteral += 1
            elif target.id == "next":
                self.sets_next = True
            self.local_defs.add(target.id)

    def visit_Assign(self, node: ast.Assign) -> None:
        for t in node.targets:
            self._record_target(t, node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._record_target(node.target, node.value)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self._record_target(node.target, None)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.local_defs.add(node.name)
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        if isinstance(node.target, ast.Name):
            self.local_defs.add(node.target.id)
        elif isinstance(node.target, ast.Tuple):
            for e in node.target.elts:
                if isinstance(e, ast.Name):
                    self.local_defs.add(e.id)
        self.generic_visit(node)

    def visit_comprehension(self, node: ast.comprehension) -> None:
        if isinstance(node.target, ast.Name):
            self.local_defs.add(node.target.id)
        elif isinstance(node.target, ast.Tuple):
            for e in node.target.elts:
                if isinstance(e, ast.Name):
                    self.local_defs.add(e.id)
        self.generic_visit(node)

    local_defs: set[str]
    imported_module_names: set[str]


def classify(code: str) -> dict:
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return {"transform": False, "reasons": [f"syntax-error:{e.lineno}"], "sets_next": False,
                "assigns_result": False, "dict_keys": [], "nonliteral_results": 0}
    v = _Purity()
    v.local_defs = set()
    v.imported_module_names = set()
    # two-pass so calls to later-defined locals don't false-flag: collect names first
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            v.local_defs.add(n.name)
        elif isinstance(n, ast.Lambda):
            pass
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    v.local_defs.add(t.id)
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            v.local_defs.add(n.target.id)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for alias in n.names:
                v.imported_module_names.add(alias.asname or alias.name.split(".")[0])
    v.visit(tree)
    pure = not v.reasons
    return {
        "transform": pure and v.assigns_result and not v.sets_next,
        "hybrid": pure and v.assigns_result and v.sets_next,
        "pure": pure,
        "reasons": sorted(set(v.reasons)),
        "sets_next": v.sets_next,
        "assigns_result": v.assigns_result,
        "dict_keys": v.result_dict_keys,
        "nonliteral_results": v.result_nonliteral,
    }


# ---------------------------------------------------------------- the sweep

def main() -> None:
    files = [
        f for f in sorted(EXAMPLES.rglob("*.pflow.md"))
        if not (set(f.parts) & EXCLUDED_DIRS)
    ]
    built = 0
    skipped: list[str] = []
    seen_code: set[str] = set()
    rows: list[dict] = []
    kind_counter: Counter[str] = Counter()

    for f in files:
        try:
            graph = resolve_validate_build(str(f), max_depth=5)
        except Exception as e:  # noqa: BLE001 — sweep tool, count and move on
            skipped.append(f"{f} ({type(e).__name__})")
            continue
        built += 1
        for node in graph.nodes:
            kind_counter[str(node.kind)] += 1
            if str(node.kind) != "code":
                continue
            code = node.params.get("code")
            if not isinstance(code, str):
                continue
            digest = hashlib.md5(code.encode()).hexdigest()[:8]
            if digest in seen_code:
                continue
            seen_code.add(digest)
            c = classify(code)
            rows.append({
                "file": str(f.relative_to(EXAMPLES)),
                "node": node.id.node_id,
                "is_decision": graph.is_decision(node.id),
                **c,
            })

    print(f"workflows: {len(files)} found, {built} built, {len(skipped)} skipped")
    for s in skipped:
        print(f"  skip: {s}")
    print(f"\nnode kinds across built graphs: {dict(kind_counter.most_common())}")

    transforms = [r for r in rows if r["transform"]]
    hybrids = [r for r in rows if r.get("hybrid")]
    opaque = [r for r in rows if not r["pure"]]
    no_result = [r for r in rows if r["pure"] and not r["assigns_result"]]

    print(f"\nunique code nodes: {len(rows)}")
    print(f"  TRANSFORM (pure, result, no next): {len(transforms)}")
    print(f"  HYBRID (pure, result + next):      {len(hybrids)}")
    print(f"  pure but no result:                {len(no_result)}")
    print(f"  NOT pure (stays CODE):             {len(opaque)}")

    reason_hist: Counter[str] = Counter()
    for r in opaque:
        for reason in r["reasons"]:
            reason_hist[reason] += 1
    print(f"\nrejection reasons: {dict(reason_hist.most_common())}")

    print("\n--- TRANSFORM nodes ---")
    for r in transforms:
        keys = r["dict_keys"]
        keyinfo = f" result-keys={keys}" if keys else (" (non-literal result)" if r["nonliteral_results"] else "")
        print(f"  {r['file']} :: {r['node']}{keyinfo}")

    print("\n--- HYBRID nodes (transform + next) ---")
    for r in hybrids:
        print(f"  {r['file']} :: {r['node']}  is_decision(model)={r['is_decision']}  result-keys={r['dict_keys']}")

    print("\n--- NOT pure ---")
    for r in opaque:
        print(f"  {r['file']} :: {r['node']}  reasons={r['reasons']}  sets_next={r['sets_next']}")

    # the is_decision gap check (validate-fix check-validate)
    print("\n--- decision flags on nodes that set next ---")
    for r in rows:
        if r["sets_next"]:
            print(f"  {r['file']} :: {r['node']}  is_decision(model)={r['is_decision']}")


if __name__ == "__main__":
    main()
