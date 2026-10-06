"""Task 118 corpus inventory: every code body pflow resolves as a Template today.

Counts the sites the task converts, per file, in four corpora:

1. ``.pflow.md`` workflow files (parsed with pflow's own markdown parser → IR nodes)
2. prose markdown that shows workflow snippets (guide, docs, architecture, instruction files)
3. Python sources (tests + src docstrings): ``"command"`` / ``"code"`` dict entries and
   ``shell command`` / ``python code`` fences inside string literals
4. everything else is reported as "manual" (f-strings, concatenations, variables)

A body "needs conversion" when ``TemplateResolver.has_templates`` is true for it — an
Expression or a ``$${`` escape (exactly what the engine resolves today).

Run from the repo root:

    uv run python .taskmaster/tasks/task_118/implementation/inventory.py            # summary
    uv run python .taskmaster/tasks/task_118/implementation/inventory.py --files    # + per-file rows
    uv run python .taskmaster/tasks/task_118/implementation/inventory.py --json out.json

Re-run it after the conversion: the "templated" columns must all read 0 outside the
allowlisted negative fixtures (tests that assert the leftover-Reference error).

Known blind spots — the scan is a map, the test suite is the oracle: a command passed
through a helper argument (`_ir("echo ${x}")`), a body built by an f-string or `.format`
(reported as "python-manual" only when a `shell command` fence is visible), and a body
whose only `${…}` is one pflow rejects today (`has_templates` is false for it).
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

from pflow.core.markdown_parser import parse_markdown
from pflow.core.templates import TemplateResolver, parse

ROOT = Path(__file__).resolve().parents[4]
SKIP_DIRS = {".venv", "node_modules", ".git", "dist", "build", ".mypy_cache", ".ruff_cache", "scratchpads"}

# A fenced block whose info string is `<lang> command` / `<lang> code` (any fence length ≥ 3).
FENCE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<fence>`{3,}|~{3,})(?P<lang>[A-Za-z0-9_+-]+)[ \t]+(?P<param>command|code)[ \t]*\n"
    r"(?P<body>.*?)\n(?P=indent)(?P=fence)[ \t]*$",
    re.DOTALL | re.MULTILINE,
)
INLINE_PARAM = re.compile(r"^[ \t]*- (?P<param>command|code):[ \t]*(?P<body>.+)$", re.MULTILINE)
SINGLE_QUOTED = re.compile(r"'[^'\n]*\$\{[^'\n]*'")


@dataclass
class Site:
    file: str
    line: int
    corpus: str  # workflow | prose | python-dict | python-fence | python-manual
    param: str  # command | code
    node: str = ""
    escape: bool = False  # contains `$${`
    refs: list[str] = field(default_factory=list)
    issues: int = 0  # `${…}` the pflow grammar rejects today (shell-only forms)
    shapes: list[str] = field(default_factory=list)  # plain | dotted | hyphenated | index | coalesce
    in_single_quotes: bool = False
    batch: bool = False
    loop: bool = False
    has_inputs: bool = False
    has_env: bool = False


def _shape(raw: str) -> str:
    if "??" in raw:
        return "coalesce"
    if "[" in raw:
        return "index"
    if "." in raw:
        return "dotted-hyphenated" if "-" in raw.split(".")[0] else "dotted"
    return "hyphenated" if "-" in raw else "plain"


def _describe(body: str, site: Site) -> Site:
    template = parse(body)
    site.escape = template.escaped
    site.refs = [expr.raw for expr in template.expressions]
    site.issues = len(template.issues)
    site.shapes = sorted({_shape(raw) for raw in site.refs})
    site.in_single_quotes = bool(SINGLE_QUOTED.search(body))
    return site


def _iter_files(suffixes: tuple[str, ...]) -> list[Path]:
    out = []
    for path in ROOT.rglob("*"):
        if path.is_file() and path.name.endswith(suffixes) and not (set(path.relative_to(ROOT).parts) & SKIP_DIRS):
            out.append(path)
    return sorted(out)


def _rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


# ── 1. workflow files ────────────────────────────────────────────────────────


def scan_workflow(path: Path, sites: list[Site], totals: Counter[str], unparsed: list[str]) -> None:
    try:
        ir = parse_markdown(path.read_text(encoding="utf-8")).ir
    except Exception as exc:  # noqa: BLE001 — invalid fixtures are expected; fall back to the fence scan
        unparsed.append(f"{_rel(path)}: {type(exc).__name__}")
        scan_prose(path, sites, totals, corpus="workflow-unparsed")
        return
    for node in ir.get("nodes", []):
        params = node.get("params") if isinstance(node.get("params"), dict) else {}
        for node_type, param in (("shell", "command"), ("code", "code")):
            body = params.get(param)
            if node.get("type") != node_type or not isinstance(body, str):
                continue
            totals[f"workflow:{param}:bodies"] += 1
            if not TemplateResolver.has_templates(body):
                continue
            source_lines = node.get("_source_lines")
            line = source_lines.get(param, 0) if isinstance(source_lines, dict) else 0
            sites.append(
                _describe(
                    body,
                    Site(
                        _rel(path),
                        int(line),
                        "workflow",
                        param,
                        node=str(node.get("id")),
                        batch=bool(node.get("batch")),
                        loop=bool(node.get("loop")),
                        has_inputs="inputs" in params,
                        has_env="env" in params,
                    ),
                )
            )


# ── 2. prose markdown (snippets, not whole workflows) ────────────────────────


def scan_prose(path: Path, sites: list[Site], totals: Counter[str], corpus: str = "prose") -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    for match in FENCE.finditer(text):
        param = match["param"]
        totals[f"{corpus}:{param}:bodies"] += 1
        if TemplateResolver.has_templates(match["body"]):
            line = text.count("\n", 0, match.start()) + 1
            sites.append(_describe(match["body"], Site(_rel(path), line, corpus, param)))
    for match in INLINE_PARAM.finditer(text):
        if TemplateResolver.has_templates(match["body"]):
            line = text.count("\n", 0, match.start()) + 1
            sites.append(_describe(match["body"], Site(_rel(path), line, f"{corpus}-inline", match["param"])))


# ── 3. Python sources ────────────────────────────────────────────────────────


class _PyScan(ast.NodeVisitor):
    def __init__(self, path: Path, sites: list[Site], totals: Counter[str]) -> None:
        self.path, self.sites, self.totals = path, sites, totals

    def visit_Dict(self, node: ast.Dict) -> None:
        for key, value in zip(node.keys, node.values, strict=True):
            if not (isinstance(key, ast.Constant) and key.value in ("command", "code")):
                continue
            param = str(key.value)
            self.totals[f"python-dict:{param}:bodies"] += 1
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                if TemplateResolver.has_templates(value.value):
                    self.sites.append(
                        _describe(value.value, Site(_rel(self.path), value.lineno, "python-dict", param))
                    )
            elif "${" in ast.unparse(value):
                self.sites.append(Site(_rel(self.path), value.lineno, "python-manual", param))
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if not isinstance(node.value, str):
            return
        for match in FENCE.finditer(node.value) if "```" in node.value else ():
            param = match["param"]
            self.totals[f"python-fence:{param}:bodies"] += 1
            if TemplateResolver.has_templates(match["body"]):
                line = node.lineno + node.value.count("\n", 0, match.start())
                self.sites.append(_describe(match["body"], Site(_rel(self.path), line, "python-fence", param)))
        # A workflow written inline in a string: `- command: echo ${x}` as a YAML param line.
        for match in INLINE_PARAM.finditer(node.value) if "- " in node.value else ():
            if TemplateResolver.has_templates(match["body"]):
                line = node.lineno + node.value.count("\n", 0, match.start())
                self.sites.append(_describe(match["body"], Site(_rel(self.path), line, "python-inline", match["param"])))

    def visit_JoinedStr(self, node: ast.JoinedStr) -> None:
        text = "".join(str(v.value) for v in node.values if isinstance(v, ast.Constant))
        if re.search(r"(shell|bash|sh) command", text) and "$" in text:
            self.sites.append(Site(_rel(self.path), node.lineno, "python-manual", "command"))
        self.generic_visit(node)


def scan_python(path: Path, sites: list[Site], totals: Counter[str]) -> None:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return
    _PyScan(path, sites, totals).visit(tree)


# ── report ───────────────────────────────────────────────────────────────────


def _area(file: str) -> str:
    parts = Path(file).parts
    if parts[0] == "src" and "guide" in parts:
        return "src/pflow/guide"
    if parts[0] in (".taskmaster", ".claude", ".agents", ".codex"):
        return "/".join(parts[:3])
    return parts[0]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--files", action="store_true", help="print one row per file")
    ap.add_argument("--sites", action="store_true", help="print one row per site")
    ap.add_argument("--json", metavar="PATH", help="write every site as JSON")
    args = ap.parse_args()

    sites: list[Site] = []
    totals: Counter[str] = Counter()
    unparsed: list[str] = []

    for path in _iter_files((".pflow.md",)):
        scan_workflow(path, sites, totals, unparsed)
    for path in _iter_files((".md", ".mdx")):
        if not path.name.endswith(".pflow.md"):
            scan_prose(path, sites, totals)
    for path in _iter_files((".py",)):
        if path != Path(__file__).resolve():
            scan_python(path, sites, totals)

    by_area: Counter[tuple[str, str, str]] = Counter((_area(s.file), s.corpus, s.param) for s in sites)
    files_by_area: dict[tuple[str, str, str], set[str]] = {}
    for s in sites:
        files_by_area.setdefault((_area(s.file), s.corpus, s.param), set()).add(s.file)

    print("== templated code bodies (need conversion), by area / corpus / param ==")
    for key in sorted(by_area):
        print(f"{by_area[key]:5d} sites in {len(files_by_area[key]):3d} files  {key[0]:40s} {key[1]:18s} {key[2]}")
    print(f"{len(sites):5d} TOTAL in {len({s.file for s in sites})} files")

    print("\n== bodies seen (templated or not) ==")
    for key in sorted(totals):
        print(f"{totals[key]:5d}  {key}")

    described = [s for s in sites if s.corpus != "python-manual"]
    print("\n== shapes (sites containing at least one such reference) ==")
    shape_counts: Counter[str] = Counter(shape for s in described for shape in s.shapes)
    for shape, count in shape_counts.most_common():
        print(f"{count:5d}  {shape}")
    print(f"{sum(s.escape for s in described):5d}  contains a $${{ escape")
    print(f"{sum(s.in_single_quotes for s in described):5d}  a reference inside single quotes")
    print(f"{sum(s.batch for s in described):5d}  on a batch step (workflow corpus only)")
    print(f"{sum(s.loop for s in described):5d}  on a loop step (workflow corpus only)")
    print(f"{sum(s.has_inputs for s in described):5d}  step already has inputs: (workflow corpus only)")
    print(f"{sum(s.has_env for s in described):5d}  step already has env: (workflow corpus only)")
    print(f"{sum(1 for s in sites if s.corpus == 'python-manual'):5d}  python-manual (f-string / expression — convert by hand)")
    print(f"{sum(s.issues > 0 for s in described):5d}  also holds a ${{…}} pflow rejects today (shell-only form)")

    if unparsed:
        print(f"\n== .pflow.md files the parser rejected ({len(unparsed)}; scanned as prose) ==")
        for row in unparsed:
            print(f"  {row}")

    if args.files:
        print("\n== per file ==")
        per_file: Counter[tuple[str, str, str]] = Counter((s.file, s.corpus, s.param) for s in sites)
        for (file, corpus, param), count in sorted(per_file.items()):
            print(f"{count:4d}  {file}  [{corpus} {param}]")
    if args.sites:
        print("\n== per site ==")
        for s in sorted(sites, key=lambda s: (s.file, s.line)):
            print(f"{s.file}:{s.line}  [{s.corpus} {s.param}] {s.node} refs={s.refs} esc={s.escape}")
    if args.json:
        Path(args.json).write_text(json.dumps([asdict(s) for s in sites], indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
